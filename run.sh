#!/bin/bash
# One command: process all CCTV clips → emit events → load into API
set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║    Store Intelligence — Full Pipeline Run           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Step 1: Process all cameras
echo "[1/3] Processing CCTV footage (YOLOv8 + ByteTrack)..."
python process_all.py --skip-frames 3
echo ""

# Step 2: Ingest into legacy tables (camera_summary, zone_stats)
echo "[2/3] Ingesting into PostgreSQL + Redis..."
python ingest.py
echo ""

# Step 3: Load pipeline events into new store_events table
echo "[3/3] Loading events into store_events API table..."
python - <<'PYEOF'
import json, glob, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
from app.ingestion import ingest_events

total_ingested = 0
for path in sorted(glob.glob("output/events_CAM_*.jsonl")):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if not events:
        print(f"  {path}: no events, skipping")
        continue
    result = ingest_events(events)
    print(f"  {path}: ingested={result['ingested']} "
          f"duplicates={result['duplicates']} errors={len(result['errors'])}")
    total_ingested += result['ingested']

print(f"\n  Total loaded into store_events: {total_ingested}")
PYEOF

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Done. Open http://localhost:8000/docs               ║"
echo "╚══════════════════════════════════════════════════════╝"
