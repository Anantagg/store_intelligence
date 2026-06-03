"""Anomaly detection for store operations.

Detects three types of anomalies:
- BILLING_QUEUE_SPIKE:  queue depth exceeds thresholds
- CONVERSION_DROP:      conversion rate falls below 15%
- DEAD_ZONE:            no visitor activity for 30+ minutes
"""

from datetime import datetime, timezone

from db.database import fetchone, fetchall
from app.metrics import get_metrics


def get_anomalies(store_id: str) -> dict:
    """Detect operational anomalies for a given store.

    Returns empty anomalies list for unknown store_ids.
    """
    anomalies = []
    now = datetime.now(timezone.utc).isoformat()

    # ── 1. BILLING_QUEUE_SPIKE ──
    r = fetchone("""
        SELECT COALESCE(MAX(queue_position), 0) AS max_q
        FROM store_events
        WHERE store_id=%s
          AND event_type IN ('queue_completed','queue_abandoned')
          AND event_ts >= NOW() - INTERVAL '2 hours'
    """, (store_id,))
    max_q = int(r["max_q"]) if r else 0
    if max_q >= 5:
        anomalies.append({
            "type":             "BILLING_QUEUE_SPIKE",
            "severity":         "CRITICAL" if max_q >= 8 else "WARN",
            "description":      f"Billing queue reached {max_q} people deep.",
            "suggested_action": "Open an additional billing counter immediately.",
            "detected_at":      now,
        })

    # ── 2. CONVERSION_DROP ──
    try:
        m = get_metrics(store_id)
        if m["unique_visitors"] >= 5 and m["conversion_rate"] < 0.15:
            anomalies.append({
                "type":             "CONVERSION_DROP",
                "severity":         "WARN",
                "description":      (
                    f"Conversion rate is {m['conversion_rate']:.1%}, "
                    f"below acceptable threshold of 15%."
                ),
                "suggested_action": (
                    "Review billing counter staffing. "
                    "Check for long wait times or product availability issues."
                ),
                "detected_at":      now,
            })
    except Exception:
        pass

    # ── 3. DEAD_ZONE ──
    dead = fetchall("""
        SELECT DISTINCT ON (zone_name) zone_name, MAX(event_ts) AS last_seen
        FROM store_events
        WHERE store_id=%s AND event_type='zone_entered' AND is_staff=FALSE
        GROUP BY zone_name
        HAVING MAX(event_ts) < NOW() - INTERVAL '30 minutes'
    """, (store_id,))
    for row in dead:
        anomalies.append({
            "type":             "DEAD_ZONE",
            "severity":         "INFO",
            "description":      f"No visitors in zone '{row['zone_name']}' for 30+ minutes.",
            "suggested_action": (
                "Check product display and stock in this zone. "
                "Consider staff-driven customer engagement."
            ),
            "detected_at":      now,
        })

    return {
        "store_id":      store_id,
        "anomaly_count": len(anomalies),
        "anomalies":     anomalies,
    }
