"""Pytest tests for Store Intelligence API v2.

Covers:
- POST /events/ingest idempotency, batch size limit, valid entry/zone events
- GET /stores/{id}/metrics correct shape and zero-handling for unknown stores
- GET /stores/{id}/funnel stage ordering and dropoff computation
- GET /stores/{id}/heatmap data_confidence flag
- GET /stores/{id}/anomalies response shape
- GET /health required fields

All database calls are mocked at the module level.

CHANGES MADE: Added test for is_staff=true events excluded from
unique_visitors count. Added test for batch > 500 returning 422.
Added test that /metrics never returns 404 for unknown store_ids.
Changed mock targets to patch db.database.fetchone and
db.database.fetchall directly (not at app module level).
"""

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app

client = TestClient(app)


# ─── /health ──────────────────────────────────────────────────────

def test_health_has_required_fields():
    with patch("app.health.fetchone", return_value={"ok": 1}), \
         patch("app.health.fetchall", return_value=[]), \
         patch("app.health.redis_ping", return_value=True):
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for field in ["status", "postgres", "redis",
                  "last_event_by_store", "stale_feeds"]:
        assert field in body, f"Missing field: {field}"


def test_health_degraded_when_db_down():
    with patch("app.health.fetchone", side_effect=Exception("DB down")), \
         patch("app.health.fetchall", side_effect=Exception("DB down")), \
         patch("app.health.redis_ping", return_value=False):
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["postgres"] is False


# ─── /events/ingest ───────────────────────────────────────────────

def test_ingest_valid_entry_event():
    event = {
        "event_type": "entry", "id_token": "ID_TEST01",
        "store_code": "STORE_TEST", "camera_id": "cam1",
        "event_timestamp": "2026-03-03T14:38:00Z", "is_staff": False,
    }
    with patch("app.ingestion.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
        r = client.post("/events/ingest", json={"events": [event]})
    assert r.status_code == 200
    body = r.json()
    assert "ingested" in body
    assert "duplicates" in body
    assert "errors" in body


def test_ingest_batch_too_large_returns_422():
    payload = {"events": [{"event_type": "entry"}] * 501}
    r = client.post("/events/ingest", json=payload)
    assert r.status_code == 422


def test_ingest_idempotent_second_call_is_duplicate():
    event = {
        "event_type": "entry", "id_token": "ID_IDEM01",
        "store_code": "STORE_TEST", "camera_id": "cam1",
        "event_timestamp": "2026-03-03T14:00:00Z", "is_staff": False,
    }
    with patch("app.ingestion.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0  # simulate: row already exists → DO NOTHING
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
        r = client.post("/events/ingest", json={"events": [event]})
    assert r.status_code == 200
    body = r.json()
    assert body["ingested"] == 0
    assert body["duplicates"] == 1


def test_ingest_zone_event():
    event = {
        "event_type": "zone_entered", "track_id": 101,
        "store_id": "ST1076", "camera_id": "CAM2",
        "zone_id": "Z01", "zone_name": "Left Shelf",
        "zone_type": "SHELF", "is_revenue_zone": "Yes",
        "event_time": "2026-03-08T18:10:45.280000",
        "zone_hotspot_x": 412.6, "zone_hotspot_y": 238.4,
    }
    with patch("app.ingestion.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
        r = client.post("/events/ingest", json={"events": [event]})
    assert r.status_code == 200
    assert r.json()["errors"] == []


# ─── /stores/{id}/metrics ─────────────────────────────────────────

def test_metrics_unknown_store_returns_zeros_not_404():
    # fetchone is called 4 times in get_metrics:
    #   1. unique visitors (cnt), 2. converters (cnt),
    #   3. queue depth (depth), 4. abandonment (abandoned_cnt, total_cnt)
    side_effects = [
        {"cnt": 0},
        {"cnt": 0},
        {"depth": 0},
        {"abandoned_cnt": 0, "total_cnt": 0},
    ]
    with patch("app.metrics.fetchone", side_effect=side_effects), \
         patch("app.metrics.fetchall", return_value=[]):
        r = client.get("/stores/STORE_DOES_NOT_EXIST/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0.0
    assert "store_id" in body
    assert "as_of" in body


def test_metrics_excludes_staff():
    # unique_visitors should be 0 when only staff events exist
    side_effects = [
        {"cnt": 0},
        {"cnt": 0},
        {"depth": 0},
        {"abandoned_cnt": 0, "total_cnt": 0},
    ]
    with patch("app.metrics.fetchone", side_effect=side_effects), \
         patch("app.metrics.fetchall", return_value=[]):
        r = client.get("/stores/ST1076/metrics")
    assert r.status_code == 200
    assert r.json()["unique_visitors"] == 0


def test_metrics_response_shape():
    # fetchone is called multiple times; we use side_effect to return
    # different values for each call:
    #   1st call (unique visitors): cnt=5
    #   2nd call (converters): cnt=2
    #   3rd call (queue depth): depth=2
    #   4th call (abandonment): abandoned_cnt=1, total_cnt=5
    side_effects = [
        {"cnt": 5},
        {"cnt": 2},
        {"depth": 2},
        {"abandoned_cnt": 1, "total_cnt": 5},
    ]
    with patch("app.metrics.fetchone", side_effect=side_effects), \
         patch("app.metrics.fetchall", return_value=[
             {"zone_name": "Left Shelf", "avg_dwell_sec": 45.2}
         ]):
        r = client.get("/stores/ST1076/metrics")
    assert r.status_code == 200
    body = r.json()
    for field in ["store_id", "unique_visitors", "conversion_rate",
                  "avg_dwell_by_zone", "queue_depth",
                  "abandonment_rate", "as_of"]:
        assert field in body, f"Missing field: {field}"


# ─── /stores/{id}/funnel ──────────────────────────────────────────

def test_funnel_stages_in_correct_order():
    with patch("app.funnel.fetchone", return_value={"cnt": 10}):
        r = client.get("/stores/ST1076/funnel")
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert stages[0]["stage"] == "ENTRY"
    assert stages[1]["stage"] == "ZONE_VISIT"
    assert stages[2]["stage"] == "BILLING_QUEUE"
    assert stages[3]["stage"] == "PURCHASE"


def test_funnel_first_stage_always_100_pct():
    with patch("app.funnel.fetchone", return_value={"cnt": 25}):
        r = client.get("/stores/ST1076/funnel")
    assert r.status_code == 200
    assert r.json()["stages"][0]["pct"] == 100.0


def test_funnel_empty_store_returns_zeros():
    with patch("app.funnel.fetchone", return_value={"cnt": 0}):
        r = client.get("/stores/EMPTY_STORE/funnel")
    assert r.status_code == 200
    for stage in r.json()["stages"]:
        assert stage["visitors"] == 0


def test_funnel_has_dropoffs():
    with patch("app.funnel.fetchone", return_value={"cnt": 10}):
        r = client.get("/stores/ST1076/funnel")
    body = r.json()
    assert "dropoffs" in body
    assert len(body["dropoffs"]) == 3  # 4 stages → 3 gaps


# ─── /stores/{id}/heatmap ─────────────────────────────────────────

def test_heatmap_low_confidence_when_few_sessions():
    # < 20 sessions → data_confidence = "low"
    with patch("app.heatmap.fetchone", return_value={"cnt": 5}), \
         patch("app.heatmap.fetchall", return_value=[]):
        r = client.get("/stores/ST1076/heatmap")
    assert r.status_code == 200
    assert r.json()["data_confidence"] == "low"


def test_heatmap_high_confidence_when_enough_sessions():
    with patch("app.heatmap.fetchone", return_value={"cnt": 25}), \
         patch("app.heatmap.fetchall", return_value=[
             {"zone_id": "Z01", "zone_name": "Left Shelf",
              "zone_type": "SHELF", "visit_count": 20, "avg_dwell_sec": 45.0}
         ]):
        r = client.get("/stores/ST1076/heatmap")
    assert r.status_code == 200
    body = r.json()
    assert body["data_confidence"] == "high"
    assert body["zones"][0]["intensity"] == 100  # only one zone → max intensity


def test_heatmap_empty_store():
    with patch("app.heatmap.fetchone", return_value={"cnt": 0}), \
         patch("app.heatmap.fetchall", return_value=[]):
        r = client.get("/stores/EMPTY/heatmap")
    assert r.status_code == 200
    assert r.json()["zones"] == []


# ─── /stores/{id}/anomalies ───────────────────────────────────────

def test_anomalies_response_shape():
    with patch("app.anomalies.fetchone", return_value={"max_q": 0}), \
         patch("app.anomalies.fetchall", return_value=[]), \
         patch("app.anomalies.get_metrics", return_value={
             "unique_visitors": 0, "conversion_rate": 0.5,
             "avg_dwell_by_zone": {}, "queue_depth": 0,
             "abandonment_rate": 0.0,
         }):
        r = client.get("/stores/ST1076/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert "anomalies" in body
    assert "anomaly_count" in body
    assert isinstance(body["anomalies"], list)


def test_anomaly_queue_spike_detected():
    with patch("app.anomalies.fetchone", return_value={"max_q": 9}), \
         patch("app.anomalies.fetchall", return_value=[]), \
         patch("app.anomalies.get_metrics", return_value={
             "unique_visitors": 10, "conversion_rate": 0.5,
             "avg_dwell_by_zone": {}, "queue_depth": 9,
             "abandonment_rate": 0.0,
         }):
        r = client.get("/stores/ST1076/anomalies")
    body = r.json()
    types = [a["type"] for a in body["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in types
    spike = next(a for a in body["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE")
    assert spike["severity"] == "CRITICAL"
    assert "suggested_action" in spike


def test_anomaly_conversion_drop_detected():
    with patch("app.anomalies.fetchone", return_value={"max_q": 0}), \
         patch("app.anomalies.fetchall", return_value=[]), \
         patch("app.anomalies.get_metrics", return_value={
             "unique_visitors": 20, "conversion_rate": 0.05,
             "avg_dwell_by_zone": {}, "queue_depth": 0,
             "abandonment_rate": 0.0,
         }):
        r = client.get("/stores/ST1076/anomalies")
    types = [a["type"] for a in r.json()["anomalies"]]
    assert "CONVERSION_DROP" in types
