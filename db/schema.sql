-- Store Intelligence — Database Schema
-- Auto-loaded by PostgreSQL on first container start via docker-entrypoint-initdb.d

-- ─── Events table: one row per CV pipeline event ───
CREATE TABLE IF NOT EXISTS events (
    id               SERIAL PRIMARY KEY,
    event_type       VARCHAR(30) NOT NULL,
    camera_id        VARCHAR(10) NOT NULL,
    track_id         INTEGER NOT NULL,
    timestamp_sec    FLOAT NOT NULL,
    frame_idx        INTEGER NOT NULL,
    zone             VARCHAR(50),
    prev_zone        VARCHAR(50),
    dwell_sec        FLOAT NOT NULL DEFAULT 0.0,
    centroid_x       FLOAT NOT NULL,
    centroid_y       FLOAT NOT NULL,
    bbox_x1          FLOAT NOT NULL,
    bbox_y1          FLOAT NOT NULL,
    bbox_x2          FLOAT NOT NULL,
    bbox_y2          FLOAT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Camera summary: one row per camera ───
CREATE TABLE IF NOT EXISTS camera_summary (
    camera_id                VARCHAR(10) PRIMARY KEY,
    total_unique_people      INTEGER NOT NULL DEFAULT 0,
    total_events             INTEGER NOT NULL DEFAULT 0,
    peak_concurrent_people   INTEGER NOT NULL DEFAULT 0,
    processed_at             TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Zone statistics: per-camera, per-zone aggregates ───
CREATE TABLE IF NOT EXISTS zone_stats (
    id                 SERIAL PRIMARY KEY,
    camera_id          VARCHAR(10) NOT NULL,
    zone_name          VARCHAR(50) NOT NULL,
    footfall_count     INTEGER NOT NULL DEFAULT 0,
    avg_dwell_sec      FLOAT NOT NULL DEFAULT 0.0,
    UNIQUE(camera_id, zone_name)
);

-- ─── Anomalies: tracks that dwelled >120s in a single zone ───
CREATE TABLE IF NOT EXISTS anomalies (
    id          SERIAL PRIMARY KEY,
    camera_id   VARCHAR(10) NOT NULL,
    track_id    INTEGER NOT NULL,
    zone        VARCHAR(50) NOT NULL,
    dwell_sec   FLOAT NOT NULL
);

-- ─── Indexes for query performance ───
CREATE INDEX IF NOT EXISTS idx_events_camera ON events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_track ON events(camera_id, track_id);
CREATE INDEX IF NOT EXISTS idx_events_zone ON events(camera_id, zone);
