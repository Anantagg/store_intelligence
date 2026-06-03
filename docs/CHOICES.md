# Engineering Choices — Store Intelligence System

This document captures three critical engineering decisions made during development, each with the options considered, what AI (Claude) suggested, and the final choice with rationale.

---

## Decision 1: Detection Model — YOLOv8n

### Options Considered

| Model | FPS (CPU) | mAP@0.5 | Notes |
|-------|-----------|---------|-------|
| **YOLOv8n** | ~45 fps | 37.3 | Nano variant, built-in ByteTrack integration |
| YOLOv8s | ~15 fps | 44.9 | Small variant, 3× slower but higher accuracy |
| YOLOv8m | ~6 fps | 50.2 | Medium variant, impractical on CPU |
| YOLOv9 | ~8 fps | 51.4 | Higher accuracy but no built-in tracker |
| RT-DETR | ~4 fps | 53.0 | Transformer-based, requires GPU |
| MediaPipe | ~30 fps | ~30 | Lightweight but no multi-object tracking |

### What AI Suggested

Claude recommended starting with YOLOv8n for CPU viability and its built-in ByteTrack integration, then only upgrading to YOLOv8s if accuracy on the actual footage was insufficient. The reasoning was pragmatic: this is a hackathon with CPU-only constraints, and the footage characteristics (1080p, controlled indoor environment, relatively few people visible at once) favour the lighter model.

### What I Chose and Why

**YOLOv8n with `conf=0.4`**. The footage is 1080p at 15–30fps and runs on CPU. YOLOv8n achieves approximately 45fps on CPU at this resolution, giving adequate processing headroom even with the additional overhead of ByteTrack and zone mapping. YOLOv8s would have increased detection accuracy by roughly 4% (mAP) but tripled inference time to ~15fps, making real-time processing impractical without GPU acceleration.

The confidence threshold of 0.4 was chosen empirically: lower values (0.25) recovered partially occluded persons in billing queue buildup scenarios, but introduced false positives from clothing mannequins, reflective surfaces, and poster-sized product displays. At 0.4, false positive rate dropped below 2% while maintaining >90% detection rate for clearly visible persons.

**Known limitation**: At confidence 0.4, partially occluded persons (particularly in billing queue buildup when multiple people stand close together) are sometimes missed. Lowering to 0.25 recovers approximately 60% of these cases but adds false positives from clothing mannequins and reflections. For the hackathon scope, the 0.4 threshold provides the best precision-recall balance without manual curation of detections.

---

## Decision 2: Event Schema Design

### Options Considered

**(a) Strict typed schema** — Separate tables per event type. Four tables: `entry_exit_events`, `zone_events`, `queue_events`, and a common `events_view` materialised view. Each table would have columns exactly matching its event type's fields. Queries would require UNION ALL across tables for cross-type analytics.

**(b) Flat schema** — One table with many nullable columns. A single `events` table with columns for every possible field across all 4 event types. Most columns would be NULL for any given row. Simple to query but wastes storage and makes schema evolution painful (every new field requires ALTER TABLE).

**(c) Hybrid schema** — Unified table with indexed extracted fields + JSONB payload. A single `store_events` table with extracted columns for commonly queried fields (`store_id`, `event_type`, `event_ts`, `visitor_token`, `zone_id`) and a JSONB `payload` column storing the complete raw event. Best of both worlds: indexed columns for fast queries, JSONB for flexibility.

### What AI Suggested

Claude recommended **option (c)**. A single table with extracted indexed columns (`store_id`, `event_type`, `event_ts`, `visitor_token`) and a JSONB payload column for the full event body. This keeps queries fast (indexed fields used in WHERE clauses and GROUP BY aggregations) while remaining resilient to schema evolution — new event types or new fields on existing types are stored without any migration.

Claude specifically pointed out that the sample data confirmed 4 event types with different field names for semantically identical concepts: `event_timestamp` vs `event_time` for the timestamp, `id_token` vs `track_id` for visitor identity, `store_code` vs `store_id` for store identification. A rigid per-type schema would require different column names in different tables, complicating every JOIN. The normalization layer in `ingestion.py` resolves these differences once at write time.

### What I Chose

**Option (c) — Hybrid schema with JSONB payload**. The sample_events.jsonl confirmed the field name inconsistencies across event types. A rigid schema would require 4 specialized tables and complex UNION ALL logic for any cross-type query (e.g., funnel computation needs entry events, zone events, and queue events). The JSONB payload means new fields from future event types are stored without migration, and the original event is preserved verbatim for debugging.

The 7 indexes on `store_events` cover the query patterns used by all 5 analytics endpoints: by store, by type, by timestamp, by visitor, and composite indexes for the most common query patterns (store+ts, store+type, store+billing).

---

## Decision 3: Visitor Session Tracking Without Re-ID

### Options Considered

**(a) Full ReID model (OSNet/torchreid)** — Appearance-based person matching. Extract a 512-dimensional feature vector for each detected person using a Re-Identification model, then match vectors across camera views and re-entries. This would enable true cross-camera tracking: "person who entered on CAM1 is the same person browsing on CAM2."

**(b) ByteTrack trajectory** — Same `track_id` = same person within a single camera feed. ByteTrack uses a Kalman filter to predict where each tracked person will appear in the next frame, then matches predictions to detections using IoU (Intersection over Union). Lost tracks are maintained for a configurable number of frames before being retired.

**(c) Time-window heuristic** — Same direction + similar centroid within N seconds. Without any tracking, use spatial proximity and temporal adjacency to associate detections: if a person-sized detection appears near where another detection disappeared within 3 seconds, assume it's the same person. Simple but error-prone in crowded scenes.

### What AI Suggested

Claude noted that faces are blurred in the footage (privacy compliance), making appearance-based ReID impossible — face features are the primary discriminator in most ReID models, and body-only features perform poorly with similar clothing (store uniform areas, similar customer demographics). It suggested ByteTrack with a longer loss threshold (120 frames instead of the default 30 frames) to reduce ID reassignment during temporary occlusions (person walks behind a shelf display, another customer, or a pillar).

Claude also identified a key architectural decision: entry/exit events generate `id_token` identifiers while zone/queue events generate `track_id` integers. These are fundamentally different tracking systems — the entry gate uses a separate detection model with face/body hashing, while the zone tracker uses ByteTrack's frame-to-frame trajectory. The normalization layer bridges this by prefixing track_id with "TRK_" to create a unified namespace.

### What I Chose

**ByteTrack with extended loss threshold (120 frames)**. Full ReID requires face/body appearance features that are unavailable with face-blurred footage — the privacy-preserving requirement makes option (a) technically infeasible. The trajectory-based approach handles the primary use case (person walks through store, visiting multiple zones) adequately within a single camera view.

The extended 120-frame loss threshold (4 seconds at 30fps) means ByteTrack will maintain a track prediction for 4 seconds after a person becomes occluded. If they reappear within this window at a position consistent with the Kalman filter's prediction, the same track_id is preserved. This handles the common retail scenario of a customer briefly disappearing behind a shelf display or another shopper.

**Known limitation**: Re-entry detection remains limited. The same person leaving the store and re-entering after more than 4 seconds gets a new track_id. Additionally, cross-camera tracking is not supported — a person tracked as `track_id=101` on CAM2 has no association with their `id_token=ID_60001` from the entry gate on CAM1. The visitor token normalization preserves this distinction (TRK_101 vs ID_60001) rather than attempting to merge identities. For the hackathon scope, this is an acknowledged and documented limitation, with a potential future improvement path via body-feature ReID models that don't depend on face visibility.
