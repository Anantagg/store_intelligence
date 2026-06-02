#!/usr/bin/env python3
"""Generate a visually annotated video for a single CCTV feed."""

import argparse
import json
import logging
import os
import sys

import cv2
import numpy as np

from pipeline.tracker import PersonTracker
from pipeline.zone_mapper import ZoneMapper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ZONE_COLORS = {
    "entrance": (255, 200, 100),
    "zone_front": (100, 255, 150),
    "zone_middle": (100, 180, 255),
    "zone_back": (180, 100, 255),
    "checkout": (100, 255, 255),
    "default": (200, 200, 200),
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate visually annotated video for CCTV feed.")
    parser.add_argument("--video", required=True, help="Path to input .mp4 file.")
    parser.add_argument("--camera-id", required=True, help="Camera identifier.")
    parser.add_argument("--skip-frames", type=int, default=3, help="Skip frames.")
    parser.add_argument("--output", help="Output annotated mp4.")
    parser.add_argument("--zones-config", default="config/zones.json", help="Path to zones.json.")
    parser.add_argument("--conf", type=float, default=0.4, help="Confidence threshold.")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLOv8 model.")
    return parser.parse_args()

def load_zones(zones_config_path: str, camera_id: str) -> dict:
    with open(zones_config_path, "r", encoding="utf-8") as f:
        all_zones = json.load(f)

    if camera_id in all_zones:
        return all_zones[camera_id]
    elif "default" in all_zones:
        return all_zones["default"]
    else:
        logger.error("No zone config found for '%s' and no 'default' key.", camera_id)
        sys.exit(1)

def run() -> None:
    args = parse_args()

    if not args.output:
        args.output = f"output/annotated_{args.camera_id}.mp4"

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    zones = load_zones(args.zones_config, args.camera_id)

    tracker = PersonTracker(model_name=args.model, conf=args.conf, device="cpu")
    zone_mapper = ZoneMapper(zones)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"✗ Error: Could not open video file '{args.video}'.", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_fps = fps / args.skip_frames
    writer = cv2.VideoWriter(args.output, fourcc, out_fps, (width, height))

    track_zone_entry = {}
    last_known_zone = {}
    all_seen_ids = set()

    frame_idx = 0
    processed_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % args.skip_frames != 0:
            frame_idx += 1
            continue

        timestamp_sec = frame_idx / fps
        tracks = tracker.process_frame(frame, frame_idx, timestamp_sec)
        
        current_tracks = []
        
        for t in tracks:
            track_id = t["track_id"]
            all_seen_ids.add(track_id)
            current_tracks.append(t)
            
            zone_name = zone_mapper.get_zone(t["centroid"])
            
            if track_id not in last_known_zone or last_known_zone[track_id] != zone_name:
                last_known_zone[track_id] = zone_name
                track_zone_entry[track_id] = timestamp_sec
                
        # --- Layer 1: Zone boundary overlays ---
        for zone_name, coords in zones.items():
            pts = np.array(coords, np.int32)
            xs = pts[:, 0]
            ys = pts[:, 1]
            x1, y1 = np.min(xs), np.min(ys)
            x2, y2 = np.max(xs), np.max(ys)
            
            color = ZONE_COLORS.get(zone_name, ZONE_COLORS["default"])
            
            overlay = frame.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            
            cv2.putText(frame, zone_name.upper(), (x1+8, y1+24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        # --- Layer 2: Person bounding boxes ---
        for t in current_tracks:
            track_id = t["track_id"]
            x1, y1, x2, y2 = t["bbox"]
            cx, cy = t["centroid"]
            zone_name = zone_mapper.get_zone([cx, cy])
            color = ZONE_COLORS.get(zone_name, (255, 255, 255)) if zone_name else (255, 255, 255)
            
            dwell_sec = timestamp_sec - track_zone_entry.get(track_id, timestamp_sec)
            
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
            
            label = f"ID:{track_id}  {dwell_sec:.1f}s"
            tw, th = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)[0]
            
            cv2.rectangle(frame, (int(x1), int(y1)-24), (int(x1)+tw+6, int(y1)), color, -1)
            cv2.putText(frame, label, (int(x1)+3, int(y1)-7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0,0,0), 2, cv2.LINE_AA)
            
            cv2.circle(frame, (int(cx), int(cy)), 5, color, -1)

        # --- Layer 3: HUD (top-right stats box) ---
        hud = frame.copy()
        cv2.rectangle(hud, (width-290, 8), (width-8, 148), (15, 15, 15), -1)
        cv2.addWeighted(hud, 0.72, frame, 0.28, 0, frame)
        
        mm = int(timestamp_sec) // 60
        ss = int(timestamp_sec) % 60
        time_str = f"{mm:02d}:{ss:02d}"
        
        hud_lines = [
            (36, 0.72, 2, args.camera_id),
            (62, 0.58, 1, f"Active:      {len(current_tracks)}"),
            (86, 0.58, 1, f"Total seen:  {len(all_seen_ids)}"),
            (110, 0.58, 1, f"Time:        {time_str}"),
            (134, 0.58, 1, f"Frame:       {frame_idx}"),
        ]
        
        for y, scale, thick, text in hud_lines:
            cv2.putText(frame, text, (width-282, y),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)

        # --- Layer 4: Frame border ---
        if len(current_tracks) > 0:
            cv2.rectangle(frame, (0, 0), (width-1, height-1), (0, 220, 100), 3)
        else:
            cv2.rectangle(frame, (0, 0), (width-1, height-1), (50, 50, 50), 3)

        # --- Write frame ---
        writer.write(frame)
        processed_count += 1
        
        if processed_count % 100 == 0:
            pct = (frame_idx / total_frames * 100) if total_frames > 0 else 0.0
            print(f"[{args.camera_id}] frame {frame_idx}/{total_frames} ({pct:.1f}%) | active: {len(current_tracks)} | total seen: {len(all_seen_ids)}")
            
        frame_idx += 1

    cap.release()
    writer.release()
    
    print(f"✓ Saved: {args.output}  ({processed_count} frames written)")

if __name__ == "__main__":
    run()
