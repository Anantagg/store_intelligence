"""Zone visit heatmap data.

Computes per-zone visit frequency and average dwell time,
normalised to 0-100 intensity scale for visualisation.
"""

from db.database import fetchone, fetchall


def get_heatmap(store_id: str) -> dict:
    """Zone visit frequency + avg dwell normalised to 0-100.

    Returns empty zones list for unknown store_ids.
    """

    session_count_r = fetchone("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt FROM store_events
        WHERE store_id=%s AND event_type='entry' AND is_staff=FALSE
    """, (store_id,))
    total_sessions = int(session_count_r["cnt"]) if session_count_r else 0
    data_confidence = "high" if total_sessions >= 20 else "low"

    rows = fetchall("""
        WITH pairs AS (
            SELECT
                z_in.zone_id,
                z_in.zone_name,
                z_in.zone_type,
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
        SELECT
            zone_id, zone_name, zone_type,
            COUNT(*)                                   AS visit_count,
            ROUND(COALESCE(AVG(dwell_sec),0)::numeric, 2) AS avg_dwell_sec
        FROM pairs
        GROUP BY zone_id, zone_name, zone_type
        ORDER BY visit_count DESC
    """, (store_id,))

    if not rows:
        return {"store_id": store_id, "zones": [], "data_confidence": data_confidence}

    max_visits = max(r["visit_count"] for r in rows) or 1
    zones = []
    for r in rows:
        zones.append({
            "zone_id":       r["zone_id"],
            "zone_name":     r["zone_name"],
            "zone_type":     r["zone_type"],
            "visit_count":   int(r["visit_count"]),
            "avg_dwell_sec": float(r["avg_dwell_sec"]),
            "intensity":     round(r["visit_count"] / max_visits * 100),
        })

    return {"store_id": store_id, "zones": zones, "data_confidence": data_confidence}
