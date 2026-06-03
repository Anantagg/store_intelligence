"""Event emitter for the Store Intelligence pipeline.

Manages per-track state, detects zone transitions, and emits structured JSON
events to a JSONL output file. Also computes summary statistics.

Emits the standardized event schema (entry, exit, zone_entered, zone_exited,
queue_completed) compatible with the Store Intelligence API v2.
"""

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime

from pipeline.zone_mapper import ZoneMapper

logger = logging.getLogger(__name__)

# Zones considered as billing/checkout areas
BILLING_ZONE_NAMES = {"checkout", "billing"}


class EventEmitter:
    """Tracks per-person state and emits structured events on state changes."""

    def __init__(self, camera_id: str, output_path: str):
        """
        Initialize the event emitter.

        Args:
            camera_id: Camera identifier string, e.g. "CAM_1".
            output_path: Path to the .jsonl output file.
        """
        self.camera_id = camera_id
        self.output_path = output_path
        self.output_file = open(output_path, "w", encoding="utf-8")

        # Per-track state: track_id → state dict
        self.track_states: dict[int, dict] = {}

        # Statistics tracking
        self.all_track_ids: set[int] = set()
        self.total_events: int = 0
        self.zone_footfall: dict[str, set[int]] = defaultdict(set)  # zone → set of track_ids
        self.zone_dwell_records: dict[str, list[float]] = defaultdict(list)  # zone → list of dwell durations
        self.concurrent_counts: list[int] = []  # track count per processed frame
        self.anomalies: list[dict] = []

        logger.info("EventEmitter initialized: camera=%s, output=%s", camera_id, output_path)

    # ── Helpers ──────────────────────────────────────────────────────

    def _ts_to_iso(self, timestamp_sec: float) -> str:
        """Convert pipeline timestamp (seconds from video start) to ISO string."""
        return datetime.utcfromtimestamp(timestamp_sec).isoformat()

    def _write_event(self, event: dict) -> None:
        """Write a single event as a JSON line and flush immediately."""
        line = json.dumps(event, ensure_ascii=False)
        self.output_file.write(line + "\n")
        self.output_file.flush()
        self.total_events += 1

    # ── Event builders (new schema) ─────────────────────────────────

    def _emit_entry(self, track_id: int, timestamp_sec: float,
                    centroid: list[float], bbox: list[float]) -> dict:
        """Emit an 'entry' event (replaces person_detected)."""
        event = {
            "event_type": "entry",
            "id_token": f"VIS_{self.camera_id}_{track_id}",
            "store_code": self.camera_id,
            "camera_id": self.camera_id,
            "event_timestamp": self._ts_to_iso(timestamp_sec),
            "is_staff": False,
            "gender_pred": None,
            "age_pred": None,
            "age_bucket": None,
            "is_face_hidden": True,
            "group_id": None,
            "group_size": None,
        }
        self._write_event(event)
        return event

    def _emit_exit(self, track_id: int, timestamp_sec: float,
                   centroid: list[float], bbox: list[float]) -> dict:
        """Emit an 'exit' event (replaces person_lost for non-billing zones)."""
        event = {
            "event_type": "exit",
            "id_token": f"VIS_{self.camera_id}_{track_id}",
            "store_code": self.camera_id,
            "camera_id": self.camera_id,
            "event_timestamp": self._ts_to_iso(timestamp_sec),
            "is_staff": False,
            "gender_pred": None,
            "age_pred": None,
            "age_bucket": None,
            "is_face_hidden": True,
            "group_id": None,
            "group_size": None,
        }
        self._write_event(event)
        return event

    def _emit_zone_entered(self, track_id: int, timestamp_sec: float,
                           zone: str, centroid: list[float],
                           bbox: list[float]) -> dict:
        """Emit a 'zone_entered' event (replaces person_entered)."""
        event = {
            "event_type": "zone_entered",
            "track_id": track_id,
            "store_id": self.camera_id,
            "camera_id": self.camera_id,
            "zone_id": f"{self.camera_id}_{zone.upper().replace(' ', '_')}",
            "zone_name": zone,
            "zone_type": "BILLING" if zone.lower() in BILLING_ZONE_NAMES else "SHELF",
            "is_revenue_zone": "Yes",
            "event_time": self._ts_to_iso(timestamp_sec),
            "zone_hotspot_x": round(centroid[0], 1),
            "zone_hotspot_y": round(centroid[1], 1),
            "gender": None,
            "age": None,
            "age_bucket": None,
        }
        self._write_event(event)
        return event

    def _emit_zone_exited(self, track_id: int, timestamp_sec: float,
                          zone: str, centroid: list[float],
                          bbox: list[float]) -> dict:
        """Emit a 'zone_exited' event (replaces person_exited)."""
        event = {
            "event_type": "zone_exited",
            "track_id": track_id,
            "store_id": self.camera_id,
            "camera_id": self.camera_id,
            "zone_id": f"{self.camera_id}_{zone.upper().replace(' ', '_')}",
            "zone_name": zone,
            "zone_type": "BILLING" if zone.lower() in BILLING_ZONE_NAMES else "SHELF",
            "is_revenue_zone": "Yes",
            "event_time": self._ts_to_iso(timestamp_sec),
            "zone_hotspot_x": round(centroid[0], 1),
            "zone_hotspot_y": round(centroid[1], 1),
            "gender": None,
            "age": None,
            "age_bucket": None,
        }
        self._write_event(event)
        return event

    def _emit_queue_completed(self, track_id: int, timestamp_sec: float,
                              zone_entry_sec: float, dwell_sec: float,
                              centroid: list[float],
                              bbox: list[float]) -> dict:
        """Emit a 'queue_completed' event (person_lost from billing zone)."""
        event = {
            "queue_event_id": str(uuid.uuid4()),
            "event_type": "queue_completed",
            "track_id": track_id,
            "store_id": self.camera_id,
            "camera_id": self.camera_id,
            "zone_id": f"{self.camera_id}_CHECKOUT",
            "zone_name": "Checkout",
            "zone_type": "BILLING",
            "is_revenue_zone": "Yes",
            "queue_join_ts": self._ts_to_iso(zone_entry_sec),
            "queue_served_ts": None,
            "queue_exit_ts": self._ts_to_iso(timestamp_sec),
            "wait_seconds": round(dwell_sec, 1),
            "queue_position_at_join": 1,
            "abandoned": False,
            "zone_hotspot_x": round(centroid[0], 1),
            "zone_hotspot_y": round(centroid[1], 1),
            "gender": None,
            "age": None,
            "age_bucket": None,
        }
        self._write_event(event)
        return event

    def _compute_dwell_sec(self, state: dict, current_sec: float) -> float:
        """Compute how many seconds this track has been in its current zone."""
        return round(current_sec - state["zone_entry_sec"], 3)

    def update(self, tracks: list[dict], zone_mapper: ZoneMapper) -> list[dict]:
        """
        Process a batch of tracks from a single frame and emit events.

        Called once per processed frame with the current list of track detections.
        Maintains internal per-track state and emits events on state changes.

        Args:
            tracks: List of track dicts from PersonTracker.process_frame().
            zone_mapper: ZoneMapper instance for centroid-to-zone mapping.

        Returns:
            List of event dicts emitted during this update.
        """
        emitted_events: list[dict] = []
        current_track_ids: set[int] = set()

        # Record concurrent count for peak tracking
        self.concurrent_counts.append(len(tracks))

        for track in tracks:
            track_id = track["track_id"]
            centroid = track["centroid"]
            bbox = track["bbox"]
            frame_idx = track["frame_idx"]
            timestamp_sec = track["timestamp_sec"]

            current_track_ids.add(track_id)
            self.all_track_ids.add(track_id)

            zone = zone_mapper.get_zone(centroid)

            if track_id not in self.track_states:
                # ── New track: entry + zone_entered ──
                self.track_states[track_id] = {
                    "zone": zone,
                    "first_seen_frame": frame_idx,
                    "first_seen_sec": timestamp_sec,
                    "zone_entry_frame": frame_idx,
                    "zone_entry_sec": timestamp_sec,
                    "last_seen_frame": frame_idx,
                    "last_seen_sec": timestamp_sec,
                    "centroid": centroid,
                    "bbox": bbox,
                }

                evt_entry = self._emit_entry(
                    track_id, timestamp_sec, centroid, bbox,
                )
                emitted_events.append(evt_entry)

                if zone is not None:
                    evt_zone_in = self._emit_zone_entered(
                        track_id, timestamp_sec, zone, centroid, bbox,
                    )
                    emitted_events.append(evt_zone_in)
                    self.zone_footfall[zone].add(track_id)

            else:
                # ── Existing track ──
                state = self.track_states[track_id]
                prev_zone = state["zone"]

                if zone != prev_zone:
                    # ── Zone transition ──
                    # Record dwell in old zone
                    if prev_zone is not None:
                        old_dwell = self._compute_dwell_sec(state, timestamp_sec)
                        self.zone_dwell_records[prev_zone].append(old_dwell)

                        # Check for anomaly (>120s dwell)
                        if old_dwell > 120.0:
                            self.anomalies.append({
                                "track_id": track_id,
                                "zone": prev_zone,
                                "dwell_sec": round(old_dwell, 3),
                            })

                        evt_zone_out = self._emit_zone_exited(
                            track_id, timestamp_sec, prev_zone, centroid, bbox,
                        )
                        emitted_events.append(evt_zone_out)

                    # NOTE: person_moved is no longer emitted — the new schema
                    # represents zone transitions as zone_exited + zone_entered.

                    if zone is not None:
                        evt_zone_in = self._emit_zone_entered(
                            track_id, timestamp_sec, zone, centroid, bbox,
                        )
                        emitted_events.append(evt_zone_in)
                        self.zone_footfall[zone].add(track_id)

                    # Update state for new zone
                    state["zone"] = zone
                    state["zone_entry_frame"] = frame_idx
                    state["zone_entry_sec"] = timestamp_sec

                else:
                    # ── Same zone — dwell heartbeat (silently skipped) ──
                    # dwell_update is not part of the required event schema.
                    pass

                # Update last seen
                state["last_seen_frame"] = frame_idx
                state["last_seen_sec"] = timestamp_sec
                state["centroid"] = centroid
                state["bbox"] = bbox

        # ── Check for lost tracks ──
        # We need the current frame_idx from any track; if no tracks, we can't check
        if tracks:
            ref_frame_idx = tracks[0]["frame_idx"]
            ref_timestamp_sec = tracks[0]["timestamp_sec"]
            lost_ids = []

            for tid, state in self.track_states.items():
                if tid not in current_track_ids:
                    frames_since = ref_frame_idx - state["last_seen_frame"]
                    if frames_since > 60:
                        # Record dwell for the zone they were in
                        if state["zone"] is not None:
                            final_dwell = self._compute_dwell_sec(state, state["last_seen_sec"])
                            self.zone_dwell_records[state["zone"]].append(final_dwell)
                            if final_dwell > 120.0:
                                self.anomalies.append({
                                    "track_id": tid,
                                    "zone": state["zone"],
                                    "dwell_sec": round(final_dwell, 3),
                                })

                        # Emit exit or queue_completed depending on last zone
                        last_zone = state["zone"]
                        dwell = self._compute_dwell_sec(state, state["last_seen_sec"])
                        if last_zone is not None and last_zone.lower() in BILLING_ZONE_NAMES:
                            evt = self._emit_queue_completed(
                                tid, ref_timestamp_sec,
                                state["zone_entry_sec"], dwell,
                                state["centroid"], state["bbox"],
                            )
                        else:
                            evt = self._emit_exit(
                                tid, ref_timestamp_sec,
                                state["centroid"], state["bbox"],
                            )
                        emitted_events.append(evt)
                        lost_ids.append(tid)

            for tid in lost_ids:
                del self.track_states[tid]

        return emitted_events

    def finalize(self, final_frame_idx: int, final_timestamp_sec: float) -> None:
        """
        Finalize the pipeline at end of video.

        Emits person_exited and person_lost for every track still in state,
        records their dwell times, and closes the output file.

        Args:
            final_frame_idx: The last frame index processed.
            final_timestamp_sec: The last timestamp in seconds.
        """
        for tid, state in list(self.track_states.items()):
            if state["zone"] is not None:
                final_dwell = self._compute_dwell_sec(state, final_timestamp_sec)
                self.zone_dwell_records[state["zone"]].append(final_dwell)
                if final_dwell > 120.0:
                    self.anomalies.append({
                        "track_id": tid,
                        "zone": state["zone"],
                        "dwell_sec": round(final_dwell, 3),
                    })

                self._emit_zone_exited(
                    tid, final_timestamp_sec, state["zone"],
                    state["centroid"], state["bbox"],
                )

            # Emit exit or queue_completed depending on last zone
            last_zone = state["zone"]
            dwell = self._compute_dwell_sec(state, state["last_seen_sec"])
            if last_zone is not None and last_zone.lower() in BILLING_ZONE_NAMES:
                self._emit_queue_completed(
                    tid, final_timestamp_sec,
                    state["zone_entry_sec"], dwell,
                    state["centroid"], state["bbox"],
                )
            else:
                self._emit_exit(
                    tid, final_timestamp_sec,
                    state["centroid"], state["bbox"],
                )

        self.track_states.clear()
        self.output_file.close()
        logger.info("EventEmitter finalized: %d total events written to %s",
                     self.total_events, self.output_path)

    def get_summary(self) -> dict:
        """
        Compute and return summary statistics for the entire video.

        Returns:
            Dict with keys:
                - camera_id (str)
                - total_unique_people (int)
                - total_events (int)
                - zone_footfall (dict[str, int]): unique people per zone
                - zone_avg_dwell_sec (dict[str, float]): average dwell time per zone
                - peak_concurrent_people (int)
                - anomalies (list[dict]): tracks that dwelled >120s in a single zone
        """
        zone_footfall_counts = {
            zone: len(track_ids)
            for zone, track_ids in self.zone_footfall.items()
        }

        zone_avg_dwell = {}
        for zone, dwells in self.zone_dwell_records.items():
            if dwells:
                zone_avg_dwell[zone] = round(sum(dwells) / len(dwells), 3)
            else:
                zone_avg_dwell[zone] = 0.0

        peak = max(self.concurrent_counts) if self.concurrent_counts else 0

        return {
            "camera_id": self.camera_id,
            "total_unique_people": len(self.all_track_ids),
            "total_events": self.total_events,
            "zone_footfall": zone_footfall_counts,
            "zone_avg_dwell_sec": zone_avg_dwell,
            "peak_concurrent_people": peak,
            "anomalies": self.anomalies,
        }
