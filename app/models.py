"""Pydantic request/response schemas for Store Intelligence API v2."""

from pydantic import BaseModel
from typing import Any


class EventIngestRequest(BaseModel):
    """Batch ingest request — array of raw event dicts."""
    events: list[dict[str, Any]]


class IngestResponse(BaseModel):
    """Ingest result summary."""
    ingested: int
    duplicates: int
    errors: list[dict]
