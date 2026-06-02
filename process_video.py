#!/usr/bin/env python3
"""Process a single CCTV video through the Store Intelligence pipeline.

CLI entry point that orchestrates detection, tracking, zone mapping,
and event emission for one camera feed.

Usage:
    python process_video.py --video videos/CAM_1.mp4 --camera-id CAM_1
    python process_video.py --video videos/CAM_2.mp4 --camera-id CAM_2 --skip-frames 2
"""

import argparse
import json
import logging
import os
import sys

import cv2

from pipeline.tracker import PersonTracker
from pipeline.zone_mapper import ZoneMapper
from pipeline.event_emitter import EventEmitter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Process a single CCTV video through the Store Intelligence pipeline.",
    )
    parser.add_argument(
        "--video", required=True,
        help="Path to the .mp4 video file.",
    )
    parser.add_argument(
        "--camera-id", required=True,
        help='Camera identifier string, e.g. "CAM_1".',
    )
    parser.add_argument(
        "--skip-frames", type=int, default=3,
        help="Process every Nth frame (default: 3).",
    )
    parser.add_argument(
        "--zones-config", default="config/zones.json",
        help="Path to the zones JSON config file (default: config/zones.json).",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Directory for output files (default: output/).",
    )
    parser.add_argument(
        "--model", default="yolov8n.pt",
        help="YOLOv8 model name (default: yolov8n.pt).",
    )
    parser.add_argument(
        "--conf", type=float, default=0.4,
        help="Detection confidence threshold (default: 0.4).",
    )
    return parser.parse_args()


def load_zones(zones_config_path: str, camera_id: str) -> dict:
    """
    Load zone polygons from the config file.

    Uses camera-specific key if present, otherwise falls back to "default".
    """
    with open(zones_config_path, "r", encoding="utf-8") as f:
        all_zones = json.load(f)

    if camera_id in all_zones:
        logger.info("Using camera-specific zone config for '%s'.", camera_id)
        return all_zones[camera_id]
    elif "default" in all_zones:
        logger.info("No zone config for '%s' — using 'default'.", camera_id)
        return all_zones["default"]
    else:
        logger.error("No zone config found for '%s' and no 'default' key.", camera_id)
        sys.exit(1)


def run(args: argparse.Namespace) -> None:
    """Execute the full pipeline for a single video."""

    # ── 1. Load zone config ──
    zones = load_zones(args.zones_config, args.camera_id)

    # ── 2. Create output directory ──
    os.makedirs(args.output_dir, exist_ok=True)

    events_path = os.path.join(args.output_dir, f"events_{args.camera_id}.jsonl")
    summary_path = os.path.join(args.output_dir, f"summary_{args.camera_id}.json")

    # ── 3. Instantiate components ──
    tracker = PersonTracker(model_name=args.model, conf=args.conf, device="cpu")
    zone_mapper = ZoneMapper(zones)
    emitter = EventEmitter(camera_id=args.camera_id, output_path=events_path)

    # ── 4. Open video ──
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"✗ Error: Could not open video file '{args.video}'.", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        fps = 30.0  # safe fallback
        logger.warning("Could not read FPS from video — defaulting to %.1f.", fps)

    print(f"▶ Processing {args.camera_id}: {args.video}")
    print(f"  {total_frames} frames @ {fps:.1f} fps | skip={args.skip_frames} → ~{fps/args.skip_frames:.1f} effective fps")

    # ── 5. Frame loop ──
    frame_idx = 0
    processed_count = 0
    last_processed_frame = 0
    last_processed_sec = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % args.skip_frames == 0:
            timestamp_sec = frame_idx / fps

            tracks = tracker.process_frame(frame, frame_idx, timestamp_sec)
            emitter.update(tracks, zone_mapper)

            processed_count += 1
            last_processed_frame = frame_idx
            last_processed_sec = timestamp_sec

            if processed_count % 100 == 0:
                pct = (frame_idx / total_frames * 100) if total_frames > 0 else 0
                active = len(emitter.track_states)
                print(f"  [{args.camera_id}] frame {frame_idx}/{total_frames} ({pct:.1f}%) | active tracks: {active}")

        frame_idx += 1

    cap.release()

    # ── 6. Finalize ──
    emitter.finalize(last_processed_frame, last_processed_sec)

    # ── 7. Write summary ──
    summary = emitter.get_summary()
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ── 8. Print final summary ──
    print(f"✓ {args.camera_id} done. "
          f"{summary['total_unique_people']} people detected, "
          f"{summary['total_events']} events, "
          f"peak {summary['peak_concurrent_people']} concurrent.")
    print(f"  Events → {events_path}")
    print(f"  Summary → {summary_path}")


if __name__ == "__main__":
    args = parse_args()
    run(args)
