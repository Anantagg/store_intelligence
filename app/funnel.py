"""Entry-to-purchase conversion funnel.

Stages:
  ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE

Each stage counts unique visitors. Dropoff between stages is computed
to identify where the store loses potential customers.
"""

from db.database import fetchone


def get_funnel(store_id: str) -> dict:
    """Compute entry-to-purchase conversion funnel.

    Session (unique visitor_token) is the unit.
    Returns zeros for unknown store_ids.
    """

    def count(query, params):
        r = fetchone(query, params)
        return int(r["cnt"]) if r else 0

    entry_count = count("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt FROM store_events
        WHERE store_id=%s AND event_type='entry' AND is_staff=FALSE
    """, (store_id,))

    zone_count = count("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt FROM store_events
        WHERE store_id=%s AND event_type='zone_entered' AND is_staff=FALSE
    """, (store_id,))

    billing_count = count("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt FROM store_events
        WHERE store_id=%s AND event_type IN ('queue_completed','queue_abandoned')
    """, (store_id,))

    purchase_count = count("""
        SELECT COUNT(DISTINCT visitor_token) AS cnt FROM store_events
        WHERE store_id=%s AND event_type='queue_completed'
        AND (abandoned IS NULL OR abandoned=FALSE)
    """, (store_id,))

    def pct(n):
        return round(n / entry_count * 100, 1) if entry_count > 0 else 0.0

    stages = [
        {"stage": "ENTRY",         "visitors": entry_count,    "pct": 100.0},
        {"stage": "ZONE_VISIT",    "visitors": zone_count,     "pct": pct(zone_count)},
        {"stage": "BILLING_QUEUE", "visitors": billing_count,  "pct": pct(billing_count)},
        {"stage": "PURCHASE",      "visitors": purchase_count, "pct": pct(purchase_count)},
    ]

    dropoffs = []
    for i in range(len(stages) - 1):
        a, b = stages[i], stages[i + 1]
        dropped = a["visitors"] - b["visitors"]
        dropoffs.append({
            "from":        a["stage"],
            "to":          b["stage"],
            "dropped":     max(dropped, 0),
            "dropoff_pct": round((dropped / a["visitors"] * 100), 1) if a["visitors"] > 0 else 0.0,
        })

    return {
        "store_id": store_id,
        "stages":   stages,
        "dropoffs": dropoffs,
    }
