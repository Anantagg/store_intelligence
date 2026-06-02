"""FastAPI application — Store Intelligence API.

Mounts all route modules and provides health/root endpoints.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import database as db
from redis_store import client as rc
from api.routes import footfall, heatmap, dwell, anomalies, events, summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="Store Intelligence API",
    version="1.0.0",
    description="Real-time store analytics from CCTV footage",
)

# ── CORS — allow all origins for dashboard development ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount routers ──
app.include_router(footfall.router, prefix="/api", tags=["footfall"])
app.include_router(heatmap.router, prefix="/api", tags=["heatmap"])
app.include_router(dwell.router, prefix="/api", tags=["dwell"])
app.include_router(anomalies.router, prefix="/api", tags=["anomalies"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(summary.router, prefix="/api", tags=["summary"])


@app.get("/")
def root():
    """Root endpoint — API info."""
    return {"message": "Store Intelligence API", "docs": "/docs"}


@app.get("/health")
def health():
    """Health check — reports status of PostgreSQL and Redis connections."""
    # Check PostgreSQL
    pg_ok = False
    try:
        result = db.fetchone("SELECT 1 AS ok")
        pg_ok = result is not None
    except Exception:
        pg_ok = False

    # Check Redis
    redis_ok = rc.ping()

    # Last updated
    last_updated = rc.get_str("last_updated")

    return {
        "status": "ok" if (pg_ok and redis_ok) else "degraded",
        "postgres": pg_ok,
        "redis": redis_ok,
        "last_updated": last_updated,
    }
