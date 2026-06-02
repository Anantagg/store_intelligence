"""Footfall endpoint — zone-level people counts."""

from fastapi import APIRouter, HTTPException, Query

from redis_store import client as rc

router = APIRouter()

CAMERAS = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]


@router.get("/footfall")
def get_footfall(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
    zone: str | None = Query(None, description="Filter to a specific zone"),
):
    """
    Get footfall (unique people count) per zone.

    If camera_id is given, returns data for that camera.
    If omitted, returns merged data across all cameras.
    """
    try:
        if camera_id:
            data = rc.get_json(f"footfall:{camera_id}")
            if data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for camera_id {camera_id}. Run ingest.py first.",
                )
            if zone:
                data = {zone: data[zone]} if zone in data else {}
            return {
                "camera_id": camera_id,
                "footfall": data,
                "total": sum(data.values()),
            }
        else:
            # Merge across all cameras
            merged: dict[str, int] = {}
            by_camera: dict[str, dict] = {}

            for cam in CAMERAS:
                cam_data = rc.get_json(f"footfall:{cam}")
                if cam_data is None:
                    continue
                by_camera[cam] = cam_data
                for z, count in cam_data.items():
                    merged[z] = merged.get(z, 0) + count

            if zone:
                merged = {zone: merged[zone]} if zone in merged else {}

            return {
                "camera_id": "ALL",
                "footfall": merged,
                "total": sum(merged.values()),
                "by_camera": by_camera,
            }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Cache unavailable")
