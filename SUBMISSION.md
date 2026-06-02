# Submission Notes — Purplle Tech Challenge 2026

## What was built
End-to-end Store Intelligence System processing 5 CCTV feeds through a
CV pipeline (YOLOv8n + ByteTrack), storing structured events in PostgreSQL,
caching analytics in Redis, and serving them through a FastAPI backend
with a live Chart.js dashboard.

## Quick start (from scratch)
```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Process all 5 camera feeds (place .mp4 files in videos/ first)
python process_all.py --skip-frames 3

# 3. Start services
docker-compose up -d

# 4. Load data into PostgreSQL + Redis
python ingest.py

# 5. Open dashboard
open http://localhost:3000
# API docs: http://localhost:8000/docs
```

## Camera coverage
| Camera | People | Events | Notes |
|--------|--------|--------|-------|
| CAM_1  | 18     | 615    | Main floor |
| CAM_2  | 45     | 916    | Highest footfall |
| CAM_3  | 30     | 312    | Side aisle |
| CAM_4  | 0      | 0      | Empty warehouse — no customers in footage |
| CAM_5  | 21     | 220    | Checkout area |
| Total  | 114    | 2063   | Across ~11 minutes of footage |

## Key design decisions
See README.md → Architectural Decisions section.

## Known limitations
- Zone polygons are horizontal bands (proxy for real shelf layout).
  Production deployment would need a polygon editor UI.
- Processing is offline batch. Real-time streaming needs a persistent
  worker process + WebSocket pipeline.
- No cross-camera re-identification — the same person is counted
  separately on each camera feed.

## Time spent
~20 hours across 5 days.
