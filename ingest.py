#!/usr/bin/env python3
"""Ingest Day 1 pipeline output into PostgreSQL and Redis.

Reads events_CAM_X.jsonl and summary_CAM_X.json from the output directory,
loads them into the database and cache layer. Idempotent — safe to re-run.

Usage:
    python ingest.py
    python ingest.py --output-dir output --summary-dir output
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from db import database as db
from redis_store import client as rc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CAMERAS = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]
BATCH_SIZE = 500

INSERT_EVENT_SQL = """
    INSERT INTO events (
        event_type, camera_id, track_id, timestamp_sec, frame_idx,
        zone, prev_zone, dwell_sec,
        centroid_x, centroid_y,
        bbox_x1, bbox_y1, bbox_x2, bbox_y2
    ) VALUES (
        %(event_type)s, %(camera_id)s, %(track_id)s, %(timestamp_sec)s, %(frame_idx)s,
        %(zone)s, %(prev_zone)s, %(dwell_sec)s,
        %(centroid_x)s, %(centroid_y)s,
        %(bbox_x1)s, %(bbox_y1)s, %(bbox_x2)s, %(bbox_y2)s
    )
"""

UPSERT_SUMMARY_SQL = """
    INSERT INTO camera_summary (camera_id, total_unique_people, total_events, peak_concurrent_people, processed_at)
    VALUES (%(camera_id)s, %(total_unique_people)s, %(total_events)s, %(peak_concurrent_people)s, NOW())
    ON CONFLICT (camera_id) DO UPDATE SET
        total_unique_people = EXCLUDED.total_unique_people,
        total_events = EXCLUDED.total_events,
        peak_concurrent_people = EXCLUDED.peak_concurrent_people,
        processed_at = NOW()
"""

UPSERT_ZONE_SQL = """
    INSERT INTO zone_stats (camera_id, zone_name, footfall_count, avg_dwell_sec)
    VALUES (%(camera_id)s, %(zone_name)s, %(footfall_count)s, %(avg_dwell_sec)s)
    ON CONFLICT (camera_id, zone_name) DO UPDATE SET
        footfall_count = EXCLUDED.footfall_count,
        avg_dwell_sec = EXCLUDED.avg_dwell_sec
"""

INSERT_ANOMALY_SQL = """
    INSERT INTO anomalies (camera_id, track_id, zone, dwell_sec)
    VALUES (%(camera_id)s, %(track_id)s, %(zone)s, %(dwell_sec)s)
"""


def wait_for_postgres(retries: int = 5, delay: float = 2.0) -> None:
    """Retry connecting to PostgreSQL until success or retries exhausted."""
    for attempt in range(1, retries + 1):
        try:
            conn = db.get_connection()
            conn.close()
            logger.info("PostgreSQL connected (attempt %d).", attempt)
            return
        except Exception as exc:
            logger.warning("PostgreSQL attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay)
    logger.error("Could not connect to PostgreSQL after %d attempts.", retries)
    sys.exit(1)


def wait_for_redis(retries: int = 5, delay: float = 2.0) -> None:
    """Retry connecting to Redis until success or retries exhausted."""
    for attempt in range(1, retries + 1):
        if rc.ping():
            logger.info("Redis connected (attempt %d).", attempt)
            return
        logger.warning("Redis attempt %d/%d failed.", attempt, retries)
        if attempt < retries:
            time.sleep(delay)
    logger.error("Could not connect to Redis after %d attempts.", retries)
    sys.exit(1)


def load_events(events_path: str, camera_id: str) -> int:
    """Load JSONL events into PostgreSQL. Returns count of inserted rows."""
    # Idempotent: delete existing events for this camera first
    db.execute("DELETE FROM events WHERE camera_id = %s", (camera_id,))

    rows = []
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            rows.append({
                "event_type": event["event_type"],
                "camera_id": event["camera_id"],
                "track_id": event["track_id"],
                "timestamp_sec": event["timestamp_sec"],
                "frame_idx": event["frame_idx"],
                "zone": event.get("zone"),
                "prev_zone": event.get("prev_zone"),
                "dwell_sec": event.get("dwell_sec", 0.0),
                "centroid_x": event["centroid"][0],
                "centroid_y": event["centroid"][1],
                "bbox_x1": event["bbox"][0],
                "bbox_y1": event["bbox"][1],
                "bbox_x2": event["bbox"][2],
                "bbox_y2": event["bbox"][3],
            })

    # Batch insert
    total = len(rows)
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        db.executemany(INSERT_EVENT_SQL, batch)

    return total


def load_summary(summary_path: str, camera_id: str) -> dict:
    """Load summary JSON, upsert into camera_summary + zone_stats + anomalies. Returns the summary dict."""
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # Upsert camera_summary
    db.execute(UPSERT_SUMMARY_SQL, {
        "camera_id": camera_id,
        "total_unique_people": summary["total_unique_people"],
        "total_events": summary["total_events"],
        "peak_concurrent_people": summary["peak_concurrent_people"],
    })

    # Upsert zone_stats
    zone_footfall = summary.get("zone_footfall", {})
    zone_avg_dwell = summary.get("zone_avg_dwell_sec", {})
    all_zones = set(zone_footfall.keys()) | set(zone_avg_dwell.keys())

    for zone_name in all_zones:
        db.execute(UPSERT_ZONE_SQL, {
            "camera_id": camera_id,
            "zone_name": zone_name,
            "footfall_count": zone_footfall.get(zone_name, 0),
            "avg_dwell_sec": zone_avg_dwell.get(zone_name, 0.0),
        })

    # Idempotent: delete existing anomalies for this camera then re-insert
    db.execute("DELETE FROM anomalies WHERE camera_id = %s", (camera_id,))
    for anomaly in summary.get("anomalies", []):
        db.execute(INSERT_ANOMALY_SQL, {
            "camera_id": camera_id,
            "track_id": anomaly["track_id"],
            "zone": anomaly["zone"],
            "dwell_sec": anomaly["dwell_sec"],
        })

    return summary


def populate_redis(camera_id: str, summary: dict) -> None:
    """Populate all Redis keys for a single camera from its summary data."""
    zone_footfall = summary.get("zone_footfall", {})
    zone_avg_dwell = summary.get("zone_avg_dwell_sec", {})
    anomalies = summary.get("anomalies", [])

    # Footfall and dwell
    rc.set_json(f"footfall:{camera_id}", zone_footfall)
    rc.set_json(f"dwell:{camera_id}", zone_avg_dwell)

    # Scalars
    rc.set_str(f"peak:{camera_id}", str(summary["peak_concurrent_people"]))
    rc.set_str(f"total_people:{camera_id}", str(summary["total_unique_people"]))
    rc.set_str(f"total_events:{camera_id}", str(summary["total_events"]))

    # Anomalies
    rc.set_json(f"anomalies:{camera_id}", anomalies)

    # Heatmap: merge footfall + dwell per zone
    heatmap = {}
    all_zones = set(zone_footfall.keys()) | set(zone_avg_dwell.keys())
    for zone in all_zones:
        heatmap[zone] = {
            "footfall": zone_footfall.get(zone, 0),
            "avg_dwell_sec": zone_avg_dwell.get(zone, 0.0),
        }
    rc.set_json(f"heatmap:{camera_id}", heatmap)


def build_summary_all(output_dir: str, summary_dir: str) -> None:
    """Build and set the summary:all Redis key from all camera summaries."""
    all_summaries = []
    for camera_id in CAMERAS:
        summary_path = os.path.join(summary_dir, f"summary_{camera_id}.json")
        if not os.path.exists(summary_path):
            continue
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        # Count anomalies for this camera
        anomaly_count = len(summary.get("anomalies", []))

        all_summaries.append({
            "camera_id": camera_id,
            "total_unique_people": summary["total_unique_people"],
            "total_events": summary["total_events"],
            "peak_concurrent_people": summary["peak_concurrent_people"],
            "zone_footfall": summary.get("zone_footfall", {}),
            "zone_avg_dwell_sec": summary.get("zone_avg_dwell_sec", {}),
            "anomaly_count": anomaly_count,
        })

    rc.set_json("summary:all", all_summaries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CV pipeline output into PostgreSQL and Redis.")
    parser.add_argument("--output-dir", default="output", help="Directory containing JSONL event files.")
    parser.add_argument("--summary-dir", default="output", help="Directory containing summary JSON files.")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║          STORE INTELLIGENCE — DATA INGESTION            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # ── 1. Connect to services ──
    wait_for_postgres()
    wait_for_redis()

    # ── 2. Ensure schema exists (for cases where docker-entrypoint didn't run) ──
    schema_path = os.path.join(os.path.dirname(__file__), "db", "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
        finally:
            conn.close()
        logger.info("Schema applied/verified.")

    # ── 3. Ingest each camera ──
    total_events_all = 0
    total_people_all = 0

    for camera_id in CAMERAS:
        events_path = os.path.join(args.output_dir, f"events_{camera_id}.jsonl")
        summary_path = os.path.join(args.summary_dir, f"summary_{camera_id}.json")

        if not os.path.exists(events_path):
            print(f"  ⚠ Events file not found for {camera_id}: {events_path} — skipping.")
            continue

        if not os.path.exists(summary_path):
            print(f"  ⚠ Summary file not found for {camera_id}: {summary_path} — skipping.")
            continue

        # Load events into PostgreSQL
        event_count = load_events(events_path, camera_id)

        # Load summary into PostgreSQL
        summary = load_summary(summary_path, camera_id)

        # Populate Redis cache
        populate_redis(camera_id, summary)

        people = summary["total_unique_people"]
        total_events_all += event_count
        total_people_all += people

        print(f"  ✓ {camera_id} ingested: {event_count} events, {people} people")

    # ── 4. Build combined summary in Redis ──
    build_summary_all(args.output_dir, args.summary_dir)

    # ── 5. Set last_updated timestamp ──
    now_iso = datetime.now(timezone.utc).isoformat()
    rc.set_str("last_updated", now_iso)

    # ── 6. Final confirmation ──
    print()
    print(f"═══════════════════════════════════════════════════════════")
    print(f"  ✓ Ingestion complete: {total_events_all} total events, {total_people_all} total people")
    print(f"  ✓ PostgreSQL: events, camera_summary, zone_stats, anomalies loaded")
    print(f"  ✓ Redis: all cache keys populated")
    print(f"  ✓ last_updated: {now_iso}")
    print(f"═══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
