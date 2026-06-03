"""Real-time store metrics computation.

Queries the store_events table for:
- Unique visitors (entry events, excluding staff)
- Conversion rate (queue_completed / unique entries)
- Average dwell time per zone (zone_entered → zone_exited pairs)
- Queue depth (recent max queue_position)
- Abandonment rate (abandoned / total queue events)
"""

from datetime import datetime, timezone

from db.database import fetchone, fetchall


def get_metrics(store_id: str) -> dict:
    """Compute real-time store metrics from store_events table.

    Returns zeros for unknown store_ids (never 404).
    """

    # ── unique visitors (entry events, exclude staff) ──
    r = fetchone("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt
        FROM store_events
        WHERE store_id = %s AND event_type = 'entry' AND is_staff = FALSE
    """, (store_id,))
    unique_visitors = r["cnt"] if r else 0

    # ── converters (queue_completed and not abandoned) ──
    r = fetchone("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt
        FROM store_events
        WHERE store_id = %s AND event_type = 'queue_completed'
          AND (abandoned IS NULL OR abandoned = FALSE) AND is_staff = FALSE
    """, (store_id,))
    converters = r["cnt"] if r else 0

    conversion_rate = round(converters / unique_visitors, 4) if unique_visitors > 0 else 0.0

    # ── avg dwell per zone (pair zone_entered with zone_exited) ──
    zone_rows = fetchall("""
        WITH pairs AS (
            SELECT
                z_in.zone_name,
                EXTRACT(EPOCH FROM (z_out.event_ts - z_in.event_ts)) AS dwell_sec
            FROM store_events z_in
            JOIN store_events z_out
                ON z_in.visitor_token = z_out.visitor_token
               AND z_in.zone_id       = z_out.zone_id
               AND z_out.event_type   = 'zone_exited'
               AND z_out.event_ts     > z_in.event_ts
            WHERE z_in.store_id   = %s
              AND z_in.event_type = 'zone_entered'
              AND z_in.is_staff   = FALSE
        )
        SELECT zone_name, ROUND(AVG(dwell_sec)::numeric, 2) AS avg_dwell_sec
        FROM pairs
        GROUP BY zone_name
        ORDER BY avg_dwell_sec DESC
    """, (store_id,))
    avg_dwell_by_zone = {row["zone_name"]: float(row["avg_dwell_sec"]) for row in zone_rows}

    # ── queue depth (max queue position from recent events) ──
    r = fetchone("""
        SELECT COALESCE(MAX(queue_position), 0) AS depth
        FROM store_events
        WHERE store_id = %s
          AND event_type IN ('queue_completed', 'queue_abandoned')
          AND event_ts >= NOW() - INTERVAL '2 hours'
    """, (store_id,))
    queue_depth = int(r["depth"]) if r else 0

    # ── abandonment rate ──
    r = fetchone("""
        SELECT
            COUNT(*) FILTER (WHERE abandoned = TRUE)  AS abandoned_cnt,
            COUNT(*) AS total_cnt
        FROM store_events
        WHERE store_id = %s
          AND event_type IN ('queue_completed', 'queue_abandoned')
    """, (store_id,))
    if r and r["total_cnt"] and r["total_cnt"] > 0:
        abandonment_rate = round(r["abandoned_cnt"] / r["total_cnt"], 4)
    else:
        abandonment_rate = 0.0

    return {
        "store_id":          store_id,
        "as_of":             datetime.now(timezone.utc).isoformat(),
        "unique_visitors":   unique_visitors,
        "conversion_rate":   conversion_rate,
        "avg_dwell_by_zone": avg_dwell_by_zone,
        "queue_depth":       queue_depth,
        "abandonment_rate":  abandonment_rate,
    }
