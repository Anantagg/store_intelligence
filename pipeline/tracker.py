"""YOLOv8 + ByteTrack person tracker wrapper.

Provides a clean interface for detecting and tracking people in video frames
using the ultralytics YOLOv8 model with ByteTrack multi-object tracking.
"""

import logging
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class PersonTracker:
    """Wraps YOLOv8 detection + ByteTrack tracking for person (class 0) only."""

    def __init__(self, model_name: str = "yolov8n.pt", conf: float = 0.4, device: str = "cpu"):
        """
        Load YOLOv8 nano model for person detection.

        Args:
            model_name: Name of the YOLO model. Will be auto-downloaded on first run.
            conf: Detection confidence threshold (0–1).
            device: Inference device — "cpu" for portability, "cuda" for GPU.
        """
        self.model = YOLO(model_name)
        self.conf = conf
        self.device = device
        logger.info("PersonTracker initialized: model=%s, conf=%.2f, device=%s", model_name, conf, device)

    def process_frame(self, frame: np.ndarray, frame_idx: int, timestamp_sec: float) -> list[dict]:
        """
        Run detection + tracking on a single frame.

        Only tracks COCO class 0 (person). Uses ByteTrack via the built-in
        ultralytics tracker config.

        Args:
            frame: BGR image as a NumPy array (H, W, 3).
            frame_idx: Current frame index in the video.
            timestamp_sec: Current timestamp in seconds.

        Returns:
            List of dicts, each containing:
                - track_id (int): Unique ID assigned by ByteTrack.
                - bbox (list[float]): [x1, y1, x2, y2] in absolute pixel coords.
                - confidence (float): Detection confidence.
                - centroid (list[float]): [cx, cy] center of the bounding box.
                - frame_idx (int): The frame index.
                - timestamp_sec (float): The frame timestamp.
            Returns an empty list if no people are detected or tracking is not ready.
        """
        try:
            results = self.model.track(
                frame,
                persist=True,
                classes=[0],  # person only
                conf=self.conf,
                tracker="bytetrack.yaml",
                device=self.device,
                verbose=False,
            )

            detections = []

            if results is None or len(results) == 0:
                return detections

            result = results[0]

            # If no boxes or tracking IDs are not yet initialized, return empty
            if result.boxes is None or result.boxes.id is None:
                return detections

            boxes = result.boxes

            for i in range(len(boxes)):
                track_id = int(boxes.id[i].item())
                x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                conf = float(boxes.conf[i].item())
                cx = round((x1 + x2) / 2.0, 3)
                cy = round((y1 + y2) / 2.0, 3)

                detections.append({
                    "track_id": track_id,
                    "bbox": [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)],
                    "confidence": round(conf, 3),
                    "centroid": [cx, cy],
                    "frame_idx": frame_idx,
                    "timestamp_sec": round(timestamp_sec, 3),
                })

            return detections

        except Exception as exc:
            logger.warning("Frame %d: tracker error — %s", frame_idx, exc)
            return []
