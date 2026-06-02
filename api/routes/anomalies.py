"""Anomalies endpoint — unusually long dwell times."""

from fastapi import APIRouter, HTTPException, Query

from redis_store import client as rc

router = APIRouter()

CAMERAS = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]


@router.get("/anomalies")
def get_anomalies(
    camera_id: str | None = Query(None, description="Camera ID, e.g. CAM_1"),
    min_dwell_sec: float = Query(120.0, description="Minimum dwell seconds to qualify as anomaly"),
):
    """
    Get anomalies — tracks that dwelled longer than min_dwell_sec in a single zone.
    """
    try:
        if camera_id:
            data = rc.get_json(f"anomalies:{camera_id}")
            if data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for camera_id {camera_id}. Run ingest.py first.",
                )
            # Add camera_id to each anomaly dict and filter
            filtered = []
            for a in data:
                if a.get("dwell_sec", 0) >= min_dwell_sec:
                    filtered.append({
                        "track_id": a["track_id"],
                        "zone": a["zone"],
                        "dwell_sec": a["dwell_sec"],
                        "camera_id": camera_id,
                    })
            return {
                "camera_id": camera_id,
                "anomaly_count": len(filtered),
                "anomalies": filtered,
            }
        else:
            # All cameras
            all_anomalies = []
            for cam in CAMERAS:
                data = rc.get_json(f"anomalies:{cam}")
                if data is None:
                    continue
                for a in data:
                    if a.get("dwell_sec", 0) >= min_dwell_sec:
                        all_anomalies.append({
                            "track_id": a["track_id"],
                            "zone": a["zone"],
                            "dwell_sec": a["dwell_sec"],
                            "camera_id": cam,
                        })
            return {
                "camera_id": "ALL",
                "anomaly_count": len(all_anomalies),
                "anomalies": all_anomalies,
            }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Cache unavailable")
