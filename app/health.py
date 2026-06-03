"""System health check endpoint logic.

Validates PostgreSQL and Redis connectivity, reports last event
timestamps per store, and flags stale data feeds (>10 min lag).
"""

from datetime import datetime, timezone

from db.database import fetchone, fetchall
from redis_store.client import ping as redis_ping


def get_health() -> dict:
    """Return system health status including DB/Redis connectivity and data freshness."""

    # PostgreSQL check
    pg_ok = False
    try:
        r = fetchone("SELECT 1 AS ok")
        pg_ok = r is not None
    except Exception:
        pg_ok = False

    # Redis check
    redis_ok = redis_ping()

    # Last event timestamp per store
    last_event_by_store = {}
    stale_feeds = []
    try:
        rows = fetchall("""
            SELECT store_id, MAX(event_ts) AS last_ts
            FROM store_events
            GROUP BY store_id
        """)
        now = datetime.now(timezone.utc)
        for row in rows:
            ts = row["last_ts"]
            if ts:
                last_event_by_store[row["store_id"]] = ts.isoformat()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                lag_minutes = (now - ts).total_seconds() / 60
                if lag_minutes > 10:
                    stale_feeds.append(row["store_id"])
    except Exception:
        pass

    return {
        "status":              "ok" if (pg_ok and redis_ok) else "degraded",
        "postgres":            pg_ok,
        "redis":               redis_ok,
        "last_event_by_store": last_event_by_store,
        "stale_feeds":         stale_feeds,
    }
