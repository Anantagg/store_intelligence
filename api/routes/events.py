"""Events endpoint — paginated event log from PostgreSQL."""

from fastapi import APIRouter, HTTPException, Query

from db import database as db

router = APIRouter()


@router.get("/events")
def get_events(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
    event_type: str | None = Query(None, description="Filter by event type, e.g. person_entered"),
    zone: str | None = Query(None, description="Filter by zone name"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return (1–1000)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Query the raw events table with optional filters and pagination.

    Results are ordered by timestamp_sec ASC.
    """
    try:
        # Build WHERE clauses dynamically with parameterized queries
        conditions = []
        params = []

        if camera_id:
            conditions.append("camera_id = %s")
            params.append(camera_id)
        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        if zone:
            conditions.append("zone = %s")
            params.append(zone)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Get total count
        count_sql = f"SELECT COUNT(*) AS total FROM events {where_clause}"
        count_result = db.fetchone(count_sql, params)
        total = count_result["total"] if count_result else 0

        # Get paginated results
        data_sql = f"""
            SELECT id, event_type, camera_id, track_id, timestamp_sec, frame_idx,
                   zone, prev_zone, dwell_sec,
                   centroid_x, centroid_y,
                   bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                   created_at
            FROM events
            {where_clause}
            ORDER BY timestamp_sec ASC
            LIMIT %s OFFSET %s
        """
        data_params = params + [limit, offset]
        rows = db.fetchall(data_sql, data_params)

        # Convert datetime objects to strings for JSON serialization
        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": rows,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
