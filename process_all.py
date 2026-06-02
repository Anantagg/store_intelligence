#!/usr/bin/env python3
"""Process all 5 CCTV camera feeds sequentially through the Store Intelligence pipeline.

Runs process_video logic for each camera and prints a combined summary table at the end.

Usage:
    python process_all.py
    python process_all.py --skip-frames 5 --zones-config config/zones.json
"""

import argparse
import json
import os
import sys

from process_video import run as run_single_video

# Camera definitions: (video_path, camera_id)
CAMERAS = [
    ("videos/CAM 1.mp4", "CAM_1"),
    ("videos/CAM 2.mp4", "CAM_2"),
    ("videos/CAM 3.mp4", "CAM_3"),
    ("videos/CAM 4.mp4", "CAM_4"),
    ("videos/CAM 5.mp4", "CAM_5"),
]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Process all 5 CCTV cameras through the Store Intelligence pipeline.",
    )
    parser.add_argument(
        "--skip-frames", type=int, default=3,
        help="Process every Nth frame (default: 3).",
    )
    parser.add_argument(
        "--zones-config", default="config/zones.json",
        help="Path to the zones JSON config file (default: config/zones.json).",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Directory for output files (default: output/).",
    )
    parser.add_argument(
        "--model", default="yolov8n.pt",
        help="YOLOv8 model name (default: yolov8n.pt).",
    )
    parser.add_argument(
        "--conf", type=float, default=0.4,
        help="Detection confidence threshold (default: 0.4).",
    )
    return parser.parse_args()


def print_combined_summary(output_dir: str, cameras: list[tuple[str, str]]) -> None:
    """Load all summary JSONs and print a formatted combined summary table."""
    summaries = []
    for _, camera_id in cameras:
        summary_path = os.path.join(output_dir, f"summary_{camera_id}.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summaries.append(json.load(f))
        else:
            print(f"  ⚠ Summary not found for {camera_id}: {summary_path}")

    if not summaries:
        print("No summaries found.")
        return

    # ── Header ──
    print("\n" + "═" * 80)
    print("  COMBINED SUMMARY — ALL CAMERAS")
    print("═" * 80)

    # ── Table header ──
    header = f"{'Camera':<10} {'People':>8} {'Events':>8} {'Peak':>6} {'Anomalies':>10}"
    print(header)
    print("─" * 50)

    total_people = 0
    total_events = 0
    total_peak = 0
    total_anomalies = 0

    for s in summaries:
        cam = s["camera_id"]
        people = s["total_unique_people"]
        events = s["total_events"]
        peak = s["peak_concurrent_people"]
        anomaly_count = len(s.get("anomalies", []))

        print(f"{cam:<10} {people:>8} {events:>8} {peak:>6} {anomaly_count:>10}")

        total_people += people
        total_events += events
        total_peak = max(total_peak, peak)
        total_anomalies += anomaly_count

    print("─" * 50)
    print(f"{'TOTAL':<10} {total_people:>8} {total_events:>8} {total_peak:>6} {total_anomalies:>10}")
    print()

    # ── Zone-level breakdown ──
    all_zones = set()
    for s in summaries:
        all_zones.update(s.get("zone_footfall", {}).keys())

    if all_zones:
        print(f"{'Zone Footfall':<15}", end="")
        for s in summaries:
            print(f" {s['camera_id']:>8}", end="")
        print()
        print("─" * (15 + 9 * len(summaries)))

        for zone in sorted(all_zones):
            print(f"{zone:<15}", end="")
            for s in summaries:
                count = s.get("zone_footfall", {}).get(zone, 0)
                print(f" {count:>8}", end="")
            print()

        print()
        print(f"{'Avg Dwell (s)':<15}", end="")
        for s in summaries:
            print(f" {s['camera_id']:>8}", end="")
        print()
        print("─" * (15 + 9 * len(summaries)))

        for zone in sorted(all_zones):
            print(f"{zone:<15}", end="")
            for s in summaries:
                avg = s.get("zone_avg_dwell_sec", {}).get(zone, 0.0)
                print(f" {avg:>8.1f}", end="")
            print()

    print("\n" + "═" * 80)


def main() -> None:
    """Process all cameras sequentially and print combined summary."""
    args = parse_args()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║       STORE INTELLIGENCE — BATCH VIDEO PROCESSING          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    for idx, (video_path, camera_id) in enumerate(CAMERAS, 1):
        print(f"\n{'━' * 60}")
        print(f"  Camera {idx}/{len(CAMERAS)}: {camera_id}")
        print(f"{'━' * 60}")

        if not os.path.exists(video_path):
            print(f"  ✗ Video not found: {video_path} — skipping.")
            continue

        # Build a namespace that matches process_video's expected args
        video_args = argparse.Namespace(
            video=video_path,
            camera_id=camera_id,
            skip_frames=args.skip_frames,
            zones_config=args.zones_config,
            output_dir=args.output_dir,
            model=args.model,
            conf=args.conf,
        )

        try:
            run_single_video(video_args)
        except Exception as exc:
            print(f"  ✗ Error processing {camera_id}: {exc}")
            continue

    # ── Combined summary ──
    print_combined_summary(args.output_dir, CAMERAS)


if __name__ == "__main__":
    main()
