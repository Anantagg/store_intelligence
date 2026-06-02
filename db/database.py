"""PostgreSQL connection and query helpers using raw psycopg2.

Provides stateless helper functions — each call opens and closes its own
connection. Uses RealDictCursor so SELECT results are returned as dicts.
"""

import os
import logging

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# ── Connection parameters from environment (with defaults) ──
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "store_intel")
DB_USER = os.environ.get("DB_USER", "store_user")
DB_PASS = os.environ.get("DB_PASS", "store_pass")


def get_connection():
    """Return a new psycopg2 connection. Caller is responsible for closing."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )
    return conn


def execute(sql: str, params=None) -> None:
    """Execute a write query (INSERT/UPDATE/DELETE). Auto-commit."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def executemany(sql: str, params_list: list) -> None:
    """Execute a write query for many rows in one transaction. Batch insert."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetchall(sql: str, params=None) -> list[dict]:
    """Execute a SELECT, return list of dicts (column_name → value)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        conn.close()


def fetchone(sql: str, params=None) -> dict | None:
    """Execute a SELECT, return one dict or None."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
