# Store Intelligence System
### Purplle Tech Challenge 2026 — Round 2

An end-to-end AI pipeline that transforms raw CCTV footage into real-time store analytics — tracking customers, mapping zones, detecting anomalies, and serving live insights through a production-grade API and dashboard.

---

## Live Demo

| Service           | URL                          |
|-------------------|------------------------------|
| API (Swagger docs)| http://localhost:8000/docs   |
| Live Dashboard    | http://localhost:3000        |
| Health Check      | http://localhost:8000/health |

---

## System Architecture

```
CCTV Footage (5 cameras, 1920×1080)
         │
         ▼
┌─────────────────────────────────────────┐
│            CV Pipeline                  │
│  OpenCV → YOLOv8n → ByteTrack →        │
│  Zone Classifier → Event Emitter        │
└─────────────────────┬───────────────────┘
                      │ Structured JSON Events
          ┌───────────┼───────────┐
          ▼                       ▼
    ┌───────────┐         ┌──────────────┐
    │   Redis   │         │  PostgreSQL  │
    │ live cache│         │  event log   │
    └─────┬─────┘         └──────┬───────┘
          └───────────┬───────────┘
                      ▼
             ┌────────────────┐
             │  FastAPI (8000)│
             │  REST + Swagger│
             └───────┬────────┘
                     ▼
           ┌──────────────────┐
           │  Live Dashboard  │
           │  (Chart.js, 3000)│
           └──────────────────┘
```

---

## Architectural Decisions

### 1. Detection Model — YOLOv8n over alternatives

We evaluated the full YOLOv8 family (nano, small, medium, large) as well as older architectures including YOLOv5 and Faster R-CNN. YOLOv8n was selected because it delivers real-time inference speeds on CPU hardware — critical for a hackathon demo environment where GPU access is not guaranteed. For the specific task of person detection at 1080p resolution, YOLOv8n achieves sufficient accuracy since people are large, high-contrast objects in retail CCTV footage; the additional precision offered by YOLOv8m or YOLOv8l does not justify the 3–5× increase in inference time. Heavier two-stage detectors like Faster R-CNN were ruled out entirely — they run at 5–8 FPS on CPU versus YOLOv8n's 25–30 FPS, making them impractical for processing 2.5-minute clips from 5 cameras within a reasonable timeframe. The ultralytics library also provides a seamless integration between YOLOv8 detection and ByteTrack tracking via the `model.track()` API, eliminating the need to wire together separate detection and tracking codebases.

### 2. Tracker — ByteTrack over DeepSORT

ByteTrack was chosen over DeepSORT and vanilla SORT for its balance of accuracy and simplicity. Unlike DeepSORT, ByteTrack is appearance-free — it does not require a separate Re-Identification (ReID) feature extractor model, which would add significant latency (typically 5–15ms per frame for the ReID forward pass alone) and deployment complexity. ByteTrack's key innovation is its "second association" step: after matching high-confidence detections to existing tracks, it re-examines low-confidence detections and attempts to associate them with unmatched tracks. This recovers identities during partial occlusions — a common scenario in retail where customers pass behind shelving or other shoppers. Vanilla SORT, while simpler, relies solely on IoU-based matching and loses track IDs the moment a detection is missed for even a single frame, making dwell time calculations unreliable. ByteTrack ships built into the ultralytics library, so no external dependencies or custom integration code was needed — we simply pass `tracker="bytetrack.yaml"` to the model.

### 3. Dual Storage — Redis + PostgreSQL

The system writes every event to both Redis and PostgreSQL, each serving a distinct access pattern. Redis provides sub-millisecond reads for the live dashboard endpoints (`/api/summary`, `/api/footfall`, `/api/heatmap`, `/api/dwell-time`) — these are pre-aggregated counters and hash maps that the dashboard polls every 3 seconds, so read latency directly impacts perceived responsiveness. PostgreSQL stores the complete, immutable event log and supports the complex filtered queries needed by `/api/events` (pagination, camera filtering, time ranges) and `/api/anomalies` (aggregation with HAVING clauses on dwell duration). Serving all dashboard queries from PostgreSQL would introduce 10–50ms latency per request under load, which is noticeable on a 3-second polling cycle. Conversely, Redis alone cannot efficiently support ad-hoc SQL queries, JOIN operations, or durable storage with ACID guarantees. The dual-write pattern in `ingest.py` keeps both stores in sync during the batch ingestion phase; in a production system, this would be replaced with a write-ahead log or change-data-capture stream for stronger consistency guarantees.

### 4. Frame Sampling — every 3rd frame (10fps effective)

Processing every frame of 30fps video is computationally wasteful for retail analytics where subjects move at walking speed (roughly 1.4 m/s). At 1080p resolution with a typical retail camera field of view, a walking customer moves approximately 10–15 pixels between consecutive frames at 10fps — well within ByteTrack's IoU association window, which can tolerate up to 40–50 pixels of displacement between frames. By sampling every 3rd frame, we reduce compute by 66% (from 30fps to 10fps effective) with negligible impact on tracking accuracy or dwell time precision. This makes CPU-only processing practical: a 2.5-minute clip (4,500 frames) reduces to 1,500 inference passes, completing in under 5 minutes on a modern laptop CPU. The skip interval is configurable via the `--skip-frames` CLI argument, allowing operators to tune the tradeoff between accuracy and throughput for their specific deployment hardware.

### 5. Zone Design — horizontal bands as proxy for store layout

Without access to a real store floor plan or calibrated camera intrinsics, zones are defined as equal horizontal bands across the frame — a deliberate simplification that still demonstrates the full zone-tracking pipeline. The frame is divided into 4 horizontal zones (entrance, zone_a, zone_b, checkout) based on the assumption that most retail cameras are mounted at one end of an aisle, making horizontal position a reasonable proxy for depth into the store. This design is intentionally naive: in a production deployment, zones would be defined by overlaying the live video feed in a configuration UI and clicking polygon vertices around actual areas of interest (cosmetics shelving, skincare aisle, checkout counter). The `ZoneMapper` class in the pipeline already accepts arbitrary polygon configurations via `config/zones.json`, so upgrading from horizontal bands to real floor-plan polygons is purely a configuration change — zero code modifications required.

### 6. Event Schema Design

The pipeline emits 6 distinct event types that model the complete lifecycle of a customer visit: `person_detected` (first appearance in any frame), `person_entered` (entering a specific zone), `person_exited` (leaving a zone), `person_moved` (transitioning between zones), `dwell_update` (periodic heartbeat while stationary in a zone), and `person_lost` (track terminated after the person leaves the frame or is occluded for too long). This schema was designed so that any downstream analytics question — footfall, dwell time, zone transitions, path analysis, anomaly detection — can be answered by querying the event log without re-processing video. The `dwell_update` event fires every 30 frames (~3 seconds at 10fps) rather than continuously, bounding event volume to approximately 20 events per person per minute while still providing 3-second resolution on dwell time — more than sufficient for retail analytics where meaningful dwell begins at 30+ seconds. Each event carries a consistent payload (timestamp, camera_id, track_id, zone, coordinates) enabling uniform ingestion and indexing in PostgreSQL.

---

## API Reference

| Method | Endpoint          | Description                                   |
|--------|--------------------|-----------------------------------------------|
| GET    | `/health`          | Postgres + Redis connectivity status          |
| GET    | `/api/summary`     | Per-camera and global aggregated summary      |
| GET    | `/api/footfall`    | Unique people counted per zone                |
| GET    | `/api/heatmap`     | Zone intensity values for heatmap visualization|
| GET    | `/api/dwell-time`  | Average time spent per zone (in seconds)      |
| GET    | `/api/anomalies`   | Tracks with unusually long dwell time (>120s) |
| GET    | `/api/events`      | Paginated raw event log (from PostgreSQL)     |

---

## Running the Project

### Prerequisites

- Docker + Docker Compose
- Python 3.11+ (for running the CV pipeline locally)
- The 5 CCTV video files placed in `videos/`

### Step 1 — Process the videos (CV Pipeline)

```bash
pip install -r requirements.txt
python process_all.py --skip-frames 3
```

This generates `output/events_CAM_X.jsonl` and `output/summary_CAM_X.json` for each camera.

### Step 2 — Start all services

```bash
docker-compose up -d
```

Starts PostgreSQL, Redis, FastAPI API, and the dashboard server. The API waits for healthy database connections before accepting requests.

### Step 3 — Ingest the pipeline output

```bash
python ingest.py
```

Loads events into PostgreSQL and populates Redis caches. Safe to re-run — the ingestion is idempotent.

### Step 4 — Open the dashboard

Visit http://localhost:3000

API docs available at http://localhost:8000/docs

---

## Results

| Camera    | People Detected | Events | Peak Concurrent |
|-----------|-----------------|--------|-----------------|
| CAM_1     | 18              | 615    | 4               |
| CAM_2     | 45              | 916    | 6               |
| CAM_3     | 30              | 312    | 5               |
| CAM_4     | 0               | 0      | 0               |
| CAM_5     | 21              | 220    | 4               |
| **Total** | **114**         | **2063** | **6**         |

> **Note on CAM_4:** This camera returned 0 detections, likely due to camera angle, lighting conditions, or physical obstructions making person detection unreliable at the default confidence threshold of 0.4. Lowering the threshold to 0.25 or switching to a larger model (YOLOv8s) would likely recover detections at the cost of increased false positives. In a production system, per-camera confidence tuning would be part of the deployment calibration process.

---

## What I'd Build Next (Given More Time)

- **Real-time video streaming** — WebSocket-based frame-by-frame inference via a persistent worker process, replacing the current batch processing model. This would enable live monitoring with sub-second latency from camera to dashboard.

- **Custom zone editor UI** — A browser-based tool where operators click to define polygon vertices directly on the video frame, replacing the current horizontal-band approximation with precise zone boundaries that match the actual store layout.

- **Cross-camera re-identification** — A lightweight ReID model (e.g., OSNet) to match the same customer across multiple camera views. This would enable full journey tracking through the store, not just per-camera analytics.

- **Real-time alerting system** — Webhook and SMS notifications triggered when anomalies are detected (e.g., a customer dwelling in a high-value zone for over 3 minutes), enabling staff to respond proactively rather than reviewing dashboards after the fact.

- **Parallel processing pipeline** — A Celery + Redis task queue to process multiple camera feeds concurrently, with automatic retry on failure and progress tracking. This would reduce end-to-end processing time from serial (camera-by-camera) to parallel, scaling linearly with available CPU cores.

---

## Tech Stack

| Layer       | Technology                  |
|-------------|-----------------------------|
| Detection   | YOLOv8n (ultralytics)       |
| Tracking    | ByteTrack (built-in)        |
| Video I/O   | OpenCV                      |
| Geometry    | Shapely                     |
| Backend     | FastAPI + Uvicorn           |
| Primary DB  | PostgreSQL 15               |
| Cache       | Redis 7                     |
| Dashboard   | Vanilla JS + Chart.js       |
| Containers  | Docker + Docker Compose     |

---

## Project Structure

```
store-intelligence/
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + health check
│   └── routes/
│       ├── __init__.py
│       ├── anomalies.py        # GET /api/anomalies
│       ├── dwell.py            # GET /api/dwell-time
│       ├── events.py           # GET /api/events
│       ├── footfall.py         # GET /api/footfall
│       ├── heatmap.py          # GET /api/heatmap
│       └── summary.py          # GET /api/summary
├── config/
│   └── zones.json              # Zone polygon definitions
├── dashboard/
│   └── index.html              # Single-file live dashboard
├── db/
│   ├── __init__.py
│   ├── database.py             # PostgreSQL connection pool
│   └── schema.sql              # DDL for events table
├── pipeline/
│   ├── __init__.py
│   ├── event_emitter.py        # Event generation logic
│   ├── tracker.py              # YOLOv8 + ByteTrack wrapper
│   └── zone_mapper.py          # Polygon-based zone classification
├── redis_store/
│   ├── __init__.py
│   └── client.py               # Redis connection + cache helpers
├── docker-compose.yml          # Full stack orchestration
├── Dockerfile                  # API service container
├── .dockerignore               # Build context exclusions
├── ingest.py                   # JSONL → PostgreSQL + Redis loader
├── process_all.py              # Batch processor for all cameras
├── process_video.py            # Single-camera CV pipeline
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```
