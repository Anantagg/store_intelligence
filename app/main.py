"""Store Intelligence API v2 — FastAPI application.

Mounts all route handlers and configures structured logging middleware
with trace IDs on every request.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.models import EventIngestRequest
from app.ingestion import ingest_events
from app.metrics import get_metrics
from app.funnel import get_funnel
from app.heatmap import get_heatmap
from app.anomalies import get_anomalies
from app.health import get_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Store Intelligence API",
    version="2.0.0",
    description="Real-time store analytics — Purplle Tech Challenge 2026",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount legacy v1 routes for the dashboard ──
from api.routes import footfall, heatmap as legacy_heatmap, dwell, anomalies as legacy_anomalies, events, summary
app.include_router(footfall.router, prefix="/api", tags=["footfall"])
app.include_router(legacy_heatmap.router, prefix="/api", tags=["heatmap"])
app.include_router(dwell.router, prefix="/api", tags=["dwell"])
app.include_router(legacy_anomalies.router, prefix="/api", tags=["anomalies"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(summary.router, prefix="/api", tags=["summary"])


# ── Structured request logging middleware ──
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    start = time.time()
    response = await call_next(request)
    latency_ms = round((time.time() - start) * 1000, 1)
    store_id = request.path_params.get("store_id", "-")
    logger.info(
        "trace_id=%s store_id=%s endpoint=%s method=%s status=%s latency_ms=%s",
        trace_id, store_id, request.url.path, request.method,
        response.status_code, latency_ms,
    )
    return response


# ── Root ──
@app.get("/")
def root():
    return {"message": "Store Intelligence API v2", "docs": "/docs"}


# ── Health ──
@app.get("/health")
def health():
    try:
        return get_health()
    except Exception as exc:
        logger.error("Health check error: %s", exc)
        return {
            "status": "degraded",
            "postgres": False,
            "redis": False,
            "last_event_by_store": {},
            "stale_feeds": [],
        }


# ── Event Ingest ──
@app.post("/events/ingest")
def ingest(request: EventIngestRequest):
    if len(request.events) > 500:
        raise HTTPException(
            status_code=422,
            detail="Batch size exceeds 500 events.",
        )
    try:
        result = ingest_events(request.events)
        return result
    except Exception as exc:
        logger.error("Ingest error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── Store Metrics ──
@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str):
    try:
        return get_metrics(store_id)
    except Exception as exc:
        logger.error("Metrics error for %s: %s", store_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── Funnel ──
@app.get("/stores/{store_id}/funnel")
def funnel(store_id: str):
    try:
        return get_funnel(store_id)
    except Exception as exc:
        logger.error("Funnel error for %s: %s", store_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── Heatmap ──
@app.get("/stores/{store_id}/heatmap")
def heatmap(store_id: str):
    try:
        return get_heatmap(store_id)
    except Exception as exc:
        logger.error("Heatmap error for %s: %s", store_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── Anomalies ──
@app.get("/stores/{store_id}/anomalies")
def anomalies(store_id: str):
    try:
        return get_anomalies(store_id)
    except Exception as exc:
        logger.error("Anomalies error for %s: %s", store_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")
