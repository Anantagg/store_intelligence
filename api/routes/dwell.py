"""Dwell time endpoint — average time spent per zone."""

from fastapi import APIRouter, HTTPException, Query

from redis_store import client as rc

router = APIRouter()

CAMERAS = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]


@router.get("/dwell-time")
def get_dwell_time(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
    zone: str | None = Query(None, description="Filter to a specific zone"),
):
    """
    Get average dwell time per zone.

    Returns the zone with the highest average dwell time.
    """
    try:
        if camera_id:
            data = rc.get_json(f"dwell:{camera_id}")
            if data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for camera_id {camera_id}. Run ingest.py first.",
                )
        else:
            # Merge: average dwell across cameras per zone
            zone_totals: dict[str, list[float]] = {}
            for cam in CAMERAS:
                cam_data = rc.get_json(f"dwell:{cam}")
                if cam_data is None:
                    continue
                for z, avg in cam_data.items():
                    if z not in zone_totals:
                        zone_totals[z] = []
                    zone_totals[z].append(avg)

            data = {z: round(sum(vals) / len(vals), 3) for z, vals in zone_totals.items()}

            if not data:
                raise HTTPException(
                    status_code=404,
                    detail="No dwell data available. Run ingest.py first.",
                )

        if zone:
            data = {zone: data[zone]} if zone in data else {}

        highest = max(data, key=data.get) if data else None

        return {
            "camera_id": camera_id or "ALL",
            "dwell_time": data,
            "highest_dwell_zone": highest,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Cache unavailable")
