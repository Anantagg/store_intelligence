"""Heatmap endpoint — zone intensity data for visualization."""

from fastapi import APIRouter, HTTPException, Query

from redis_store import client as rc

router = APIRouter()

CAMERAS = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]


@router.get("/heatmap")
def get_heatmap(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
):
    """
    Get heatmap data (footfall + avg dwell + intensity) per zone.

    Intensity is footfall normalized to 0.0–1.0 where max footfall = 1.0.
    Zones are sorted by footfall descending.
    """
    try:
        if camera_id:
            data = rc.get_json(f"heatmap:{camera_id}")
            if data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for camera_id {camera_id}. Run ingest.py first.",
                )
        else:
            # Merge all cameras
            data: dict = {}
            for cam in CAMERAS:
                cam_data = rc.get_json(f"heatmap:{cam}")
                if cam_data is None:
                    continue
                for zone_name, zone_info in cam_data.items():
                    if zone_name not in data:
                        data[zone_name] = {"footfall": 0, "avg_dwell_sec": 0.0, "_dwell_count": 0}
                    data[zone_name]["footfall"] += zone_info.get("footfall", 0)
                    data[zone_name]["avg_dwell_sec"] += zone_info.get("avg_dwell_sec", 0.0)
                    data[zone_name]["_dwell_count"] += 1

            # Average the dwell times across cameras
            for zone_name in data:
                count = data[zone_name].pop("_dwell_count", 1)
                if count > 0:
                    data[zone_name]["avg_dwell_sec"] = round(
                        data[zone_name]["avg_dwell_sec"] / count, 3
                    )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="No heatmap data available. Run ingest.py first.",
            )

        # Build zone list with intensity
        max_footfall = max(z.get("footfall", 0) for z in data.values()) if data else 1
        if max_footfall == 0:
            max_footfall = 1  # avoid division by zero

        zones = []
        for zone_name, zone_info in data.items():
            ff = zone_info.get("footfall", 0)
            zones.append({
                "zone_name": zone_name,
                "footfall": ff,
                "avg_dwell_sec": round(zone_info.get("avg_dwell_sec", 0.0), 3),
                "intensity": round(ff / max_footfall, 3),
            })

        # Sort by footfall descending
        zones.sort(key=lambda z: z["footfall"], reverse=True)

        return {
            "camera_id": camera_id or "ALL",
            "zones": zones,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Cache unavailable")
