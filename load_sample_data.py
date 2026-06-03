#!/usr/bin/env python3
"""Load sample data files into the Store Intelligence database.

Usage:
    python load_sample_data.py

Steps:
    1. Apply db/schema_v2.sql to PostgreSQL
    2. Load sample_events.jsonl into store_events via ingest_events()
    3. Load pos_transactions.csv into pos_transactions table
    4. Print confirmation with counts
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import get_connection, fetchone
from app.ingestion import ingest_events


SCHEMA_V2_PATH = os.path.join(os.path.dirname(__file__), "db", "schema_v2.sql")
EVENTS_PATH = os.path.join(os.path.dirname(__file__), "sample_events.jsonl")
POS_PATH = os.path.join(os.path.dirname(__file__), "pos_transactions.csv")

POS_INSERT_SQL = """
    INSERT INTO pos_transactions
      (order_id, store_id, transaction_ts, total_amount, product_id, brand_name)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (order_id) DO NOTHING
"""


def apply_schema():
    """Apply schema_v2.sql to the database."""
    print("── Step 1: Applying db/schema_v2.sql ──")
    with open(SCHEMA_V2_PATH, "r") as f:
        sql = f.read()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("   ✓ Schema applied successfully")
    except Exception as exc:
        conn.rollback()
        print(f"   ✗ Schema error: {exc}")
        raise
    finally:
        conn.close()


def load_events():
    """Load sample_events.jsonl using the ingest_events() function."""
    print("── Step 2: Loading sample_events.jsonl ──")
    if not os.path.exists(EVENTS_PATH):
        print(f"   ✗ File not found: {EVENTS_PATH}")
        return

    events = []
    with open(EVENTS_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    print(f"   Parsed {len(events)} events from file")
    result = ingest_events(events)
    print(f"   ✓ Ingested: {result['ingested']}, "
          f"Duplicates: {result['duplicates']}, "
          f"Errors: {len(result['errors'])}")
    if result['errors']:
        for err in result['errors']:
            print(f"     Error: {err}")


def load_pos():
    """Load pos_transactions.csv into the pos_transactions table."""
    print("── Step 3: Loading pos_transactions.csv ──")
    if not os.path.exists(POS_PATH):
        print(f"   ✗ File not found: {POS_PATH}")
        return

    rows = []
    with open(POS_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse DD-MM-YYYY date and HH:MM:SS time → TIMESTAMPTZ
            order_date = row["order_date"].strip()
            order_time = row["order_time"].strip()
            try:
                dt = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError as exc:
                print(f"   ✗ Date parse error for order {row['order_id']}: {exc}")
                continue

            rows.append((
                row["order_id"].strip(),
                row["store_id"].strip(),
                dt,
                float(row["total_amount"].strip()),
                row["product_id"].strip(),
                row["brand_name"].strip(),
            ))

    conn = get_connection()
    inserted = 0
    try:
        with conn.cursor() as cur:
            for params in rows:
                cur.execute(POS_INSERT_SQL, params)
                if cur.rowcount == 1:
                    inserted += 1
        conn.commit()
        print(f"   ✓ Inserted {inserted} POS transactions ({len(rows) - inserted} duplicates)")
    except Exception as exc:
        conn.rollback()
        print(f"   ✗ POS insert error: {exc}")
        raise
    finally:
        conn.close()


def verify():
    """Print verification counts."""
    print("── Step 4: Verification ──")
    r = fetchone("SELECT COUNT(*) AS cnt FROM store_events")
    print(f"   store_events rows:    {r['cnt'] if r else 0}")

    r = fetchone("SELECT COUNT(*) AS cnt FROM pos_transactions")
    print(f"   pos_transactions rows: {r['cnt'] if r else 0}")

    r = fetchone("SELECT COUNT(DISTINCT store_id) AS cnt FROM store_events")
    print(f"   unique stores:         {r['cnt'] if r else 0}")

    r = fetchone("SELECT COUNT(DISTINCT event_type) AS cnt FROM store_events")
    print(f"   unique event types:    {r['cnt'] if r else 0}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Store Intelligence — Sample Data Loader")
    print("=" * 60)
    print()

    try:
        apply_schema()
        print()
        load_events()
        print()
        load_pos()
        print()
        verify()
        print()
        print("✓ All done!")
    except Exception as exc:
        print(f"\n✗ Fatal error: {exc}")
        sys.exit(1)
