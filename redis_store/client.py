"""Redis connection and read/write helpers.

Uses a connection pool for efficient reuse across calls.
All keys follow a strict naming convention documented in the project spec.
"""

import json
import os
import logging

import redis

logger = logging.getLogger(__name__)

# ── Connection parameters from environment ──
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# ── Shared connection pool ──
_pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)


def get_redis() -> redis.Redis:
    """Return a Redis client instance backed by the shared connection pool."""
    return redis.Redis(connection_pool=_pool)


def set_json(key: str, value, ex: int = None) -> None:
    """Serialize value to JSON and SET in Redis. ex = expiry seconds (optional)."""
    r = get_redis()
    serialized = json.dumps(value, ensure_ascii=False)
    if ex is not None:
        r.set(key, serialized, ex=ex)
    else:
        r.set(key, serialized)


def get_json(key: str):
    """GET from Redis and JSON-deserialize. Return None if key missing."""
    r = get_redis()
    raw = r.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def set_str(key: str, value: str, ex: int = None) -> None:
    """SET a plain string value."""
    r = get_redis()
    if ex is not None:
        r.set(key, value, ex=ex)
    else:
        r.set(key, value)


def get_str(key: str) -> str | None:
    """GET a plain string value. Return None if missing."""
    r = get_redis()
    return r.get(key)


def ping() -> bool:
    """Return True if Redis is reachable, False otherwise."""
    try:
        r = get_redis()
        return r.ping()
    except Exception:
        return False
