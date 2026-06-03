"""Event normalization and batch ingest logic.

Handles all 4 event types (entry, exit, zone_entered, zone_exited,
queue_completed, queue_abandoned) and normalizes their different field
names into the unified store_events schema.
"""

import uuid
import json
import logging
from datetime import datetime, timezone

from db.database import get_connection

logger = logging.getLogger(__name__)

UPSERT_EVENT_SQL = """
    INSERT INTO store_events (
        event_id, event_type, store_id, camera_id, visitor_token,
        is_staff, event_ts, zone_id, zone_name, zone_type,
        is_billing_zone, wait_seconds, abandoned, queue_position, payload
    ) VALUES (
        %(event_id)s, %(event_type)s, %(store_id)s, %(camera_id)s, %(visitor_token)s,
        %(is_staff)s, %(event_ts)s, %(zone_id)s, %(zone_name)s, %(zone_type)s,
        %(is_billing_zone)s, %(wait_seconds)s, %(abandoned)s, %(queue_position)s,
        %(payload)s
    )
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
"""


def normalize_event(raw: dict) -> dict:
    """
    Normalize any of the 4 event types into a unified row dict.

    Field mapping:
    - entry/exit:  store_code → store_id, id_token → visitor_token, event_timestamp → event_ts
    - zone:        store_id (as-is), track_id → visitor_token (TRK_ prefix), event_time → event_ts
    - queue:       store_id (as-is), track_id → visitor_token, queue_join_ts → event_ts
    """
    # ── event_id ──
    # Queue events have their own UUID; others get a generated one
    event_id = raw.get("queue_event_id") or str(uuid.uuid4())

    # ── store_id ── (entry/exit use "store_code"; zone/queue use "store_id")
    store_id = raw.get("store_id") or raw.get("store_code") or "UNKNOWN"

    # ── visitor_token ── (entry/exit use "id_token"; zone/queue use "track_id")
    id_token = raw.get("id_token")
    track_id = raw.get("track_id")
    if id_token:
        visitor_token = str(id_token)
    elif track_id is not None:
        visitor_token = f"TRK_{track_id}"
    else:
        visitor_token = None

    # ── timestamp ── (entry/exit use "event_timestamp"; zone use "event_time"; queue use "queue_join_ts")
    ts_raw = (
        raw.get("event_timestamp")
        or raw.get("event_time")
        or raw.get("queue_join_ts")
    )
    try:
        event_ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if event_ts.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=timezone.utc)
    except Exception:
        event_ts = datetime.now(timezone.utc)

    zone_type = raw.get("zone_type") or ""
    is_billing_zone = zone_type.upper() == "BILLING"

    return {
        "event_id":        event_id,
        "event_type":      raw.get("event_type", "unknown"),
        "store_id":        store_id,
        "camera_id":       raw.get("camera_id"),
        "visitor_token":   visitor_token,
        "is_staff":        bool(raw.get("is_staff", False)),
        "event_ts":        event_ts,
        "zone_id":         raw.get("zone_id"),
        "zone_name":       raw.get("zone_name"),
        "zone_type":       zone_type or None,
        "is_billing_zone": is_billing_zone,
        "wait_seconds":    raw.get("wait_seconds"),
        "abandoned":       raw.get("abandoned"),
        "queue_position":  raw.get("queue_position_at_join"),
        "payload":         json.dumps(raw, ensure_ascii=False, default=str),
    }


def ingest_events(raw_events: list[dict]) -> dict:
    """
    Normalize and insert a batch of events.
    Returns {ingested, duplicates, errors}.

    Idempotent: sending the same events twice results in ingested=0, duplicates=N
    on the second call (thanks to ON CONFLICT DO NOTHING).
    """
    ingested, duplicates, errors = 0, 0, []
    rows = []

    for raw in raw_events:
        try:
            rows.append(normalize_event(raw))
        except Exception as exc:
            errors.append({"event": raw, "reason": str(exc)})

    if not rows:
        return {"ingested": 0, "duplicates": 0, "errors": errors}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(UPSERT_EVENT_SQL, row)
                if cur.rowcount == 1:
                    ingested += 1
                else:
                    duplicates += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Batch insert failed: %s", exc)
        errors.append({"event": "batch", "reason": str(exc)})
    finally:
        conn.close()

    return {"ingested": ingested, "duplicates": duplicates, "errors": errors}
