"""Event emitter for the Store Intelligence pipeline.

Manages per-track state, detects zone transitions, and emits structured JSON
events to a JSONL output file. Also computes summary statistics.
"""

import json
import logging
from collections import defaultdict

from pipeline.zone_mapper import ZoneMapper

logger = logging.getLogger(__name__)


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

    def _make_event(
        self,
        event_type: str,
        track_id: int,
        timestamp_sec: float,
        frame_idx: int,
        zone: str | None,
        prev_zone: str | None,
        dwell_sec: float,
        centroid: list[float],
        bbox: list[float],
    ) -> dict:
        """Build a standardized event dict with all required fields."""
        return {
            "event_type": event_type,
            "camera_id": self.camera_id,
            "track_id": track_id,
            "timestamp_sec": round(timestamp_sec, 3),
            "frame_idx": frame_idx,
            "zone": zone,
            "prev_zone": prev_zone,
            "dwell_sec": round(dwell_sec, 3),
            "centroid": [round(centroid[0], 3), round(centroid[1], 3)],
            "bbox": [round(b, 3) for b in bbox],
        }

    def _write_event(self, event: dict) -> None:
        """Write a single event as a JSON line and flush immediately."""
        line = json.dumps(event, ensure_ascii=False)
        self.output_file.write(line + "\n")
        self.output_file.flush()
        self.total_events += 1

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
                # ── New track: person_detected + person_entered ──
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

                evt_detected = self._make_event(
                    "person_detected", track_id, timestamp_sec, frame_idx,
                    zone, None, 0.0, centroid, bbox,
                )
                self._write_event(evt_detected)
                emitted_events.append(evt_detected)

                if zone is not None:
                    evt_entered = self._make_event(
                        "person_entered", track_id, timestamp_sec, frame_idx,
                        zone, None, 0.0, centroid, bbox,
                    )
                    self._write_event(evt_entered)
                    emitted_events.append(evt_entered)
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

                        evt_exited = self._make_event(
                            "person_exited", track_id, timestamp_sec, frame_idx,
                            prev_zone, None, old_dwell, centroid, bbox,
                        )
                        self._write_event(evt_exited)
                        emitted_events.append(evt_exited)

                    evt_moved = self._make_event(
                        "person_moved", track_id, timestamp_sec, frame_idx,
                        zone, prev_zone, 0.0, centroid, bbox,
                    )
                    self._write_event(evt_moved)
                    emitted_events.append(evt_moved)

                    if zone is not None:
                        evt_entered = self._make_event(
                            "person_entered", track_id, timestamp_sec, frame_idx,
                            zone, prev_zone, 0.0, centroid, bbox,
                        )
                        self._write_event(evt_entered)
                        emitted_events.append(evt_entered)
                        self.zone_footfall[zone].add(track_id)

                    # Update state for new zone
                    state["zone"] = zone
                    state["zone_entry_frame"] = frame_idx
                    state["zone_entry_sec"] = timestamp_sec

                else:
                    # ── Same zone — dwell heartbeat ──
                    if frame_idx % 30 == 0:
                        dwell = self._compute_dwell_sec(state, timestamp_sec)
                        evt_dwell = self._make_event(
                            "dwell_update", track_id, timestamp_sec, frame_idx,
                            zone, None, dwell, centroid, bbox,
                        )
                        self._write_event(evt_dwell)
                        emitted_events.append(evt_dwell)

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

                        evt_lost = self._make_event(
                            "person_lost", tid, ref_timestamp_sec, ref_frame_idx,
                            state["zone"], None,
                            self._compute_dwell_sec(state, state["last_seen_sec"]),
                            state["centroid"], state["bbox"],
                        )
                        self._write_event(evt_lost)
                        emitted_events.append(evt_lost)
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

                evt_exited = self._make_event(
                    "person_exited", tid, final_timestamp_sec, final_frame_idx,
                    state["zone"], None, final_dwell,
                    state["centroid"], state["bbox"],
                )
                self._write_event(evt_exited)

            evt_lost = self._make_event(
                "person_lost", tid, final_timestamp_sec, final_frame_idx,
                state["zone"], None,
                self._compute_dwell_sec(state, state["last_seen_sec"]),
                state["centroid"], state["bbox"],
            )
            self._write_event(evt_lost)

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
