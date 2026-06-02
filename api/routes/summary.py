"""Summary endpoint — per-camera and global summary data."""

from fastapi import APIRouter, HTTPException, Query

from redis_store import client as rc

router = APIRouter()


@router.get("/summary")
def get_summary(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
):
    """
    Get summary data for one or all cameras.

    Data is read from the pre-built summary:all Redis key.
    """
    try:
        last_updated = rc.get_str("last_updated")
        all_summaries = rc.get_json("summary:all")

        if all_summaries is None:
            raise HTTPException(
                status_code=404,
                detail="No summary data available. Run ingest.py first.",
            )

        if camera_id:
            # Find the matching camera
            matched = [s for s in all_summaries if s["camera_id"] == camera_id]
            if not matched:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for camera_id {camera_id}. Run ingest.py first.",
                )
            return {
                "last_updated": last_updated,
                "cameras": matched,
            }
        else:
            return {
                "last_updated": last_updated,
                "cameras": all_summaries,
            }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Cache unavailable")
