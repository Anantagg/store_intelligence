-- ================================================================
-- Store Intelligence v2 — New tables for unified event schema
-- IMPORTANT: Uses IF NOT EXISTS everywhere. Does not drop existing tables.
-- ================================================================

-- ─── Unified event log: all 4 event types in one table ───
CREATE TABLE IF NOT EXISTS store_events (
  id              SERIAL PRIMARY KEY,
  event_id        VARCHAR(200) UNIQUE NOT NULL,
  event_type      VARCHAR(50)  NOT NULL,
  store_id        VARCHAR(100) NOT NULL,
  camera_id       VARCHAR(200),
  visitor_token   VARCHAR(200),
  is_staff        BOOLEAN      NOT NULL DEFAULT FALSE,
  event_ts        TIMESTAMPTZ  NOT NULL,
  zone_id         VARCHAR(300),
  zone_name       VARCHAR(300),
  zone_type       VARCHAR(50),
  is_billing_zone BOOLEAN      NOT NULL DEFAULT FALSE,
  wait_seconds    FLOAT,
  abandoned       BOOLEAN,
  queue_position  INTEGER,
  payload         JSONB        NOT NULL,
  ingested_at     TIMESTAMPTZ  DEFAULT NOW()
);

-- ─── Indexes for query performance ───
CREATE INDEX IF NOT EXISTS idx_se_store      ON store_events(store_id);
CREATE INDEX IF NOT EXISTS idx_se_type       ON store_events(event_type);
CREATE INDEX IF NOT EXISTS idx_se_ts         ON store_events(event_ts);
CREATE INDEX IF NOT EXISTS idx_se_visitor    ON store_events(visitor_token);
CREATE INDEX IF NOT EXISTS idx_se_store_ts   ON store_events(store_id, event_ts);
CREATE INDEX IF NOT EXISTS idx_se_store_type ON store_events(store_id, event_type);
CREATE INDEX IF NOT EXISTS idx_se_billing    ON store_events(store_id, is_billing_zone);

-- ─── POS transaction data ───
CREATE TABLE IF NOT EXISTS pos_transactions (
  id              SERIAL PRIMARY KEY,
  order_id        VARCHAR(100) UNIQUE,
  store_id        VARCHAR(100) NOT NULL,
  transaction_ts  TIMESTAMPTZ  NOT NULL,
  total_amount    FLOAT,
  product_id      VARCHAR(100),
  brand_name      VARCHAR(200),
  ingested_at     TIMESTAMPTZ  DEFAULT NOW()
);

-- ─── POS indexes ───
CREATE INDEX IF NOT EXISTS idx_pos_store ON pos_transactions(store_id);
CREATE INDEX IF NOT EXISTS idx_pos_ts    ON pos_transactions(transaction_ts);
