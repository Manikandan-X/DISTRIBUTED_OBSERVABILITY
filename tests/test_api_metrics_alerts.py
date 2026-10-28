from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.timeutils import utcnow
from app.db.session import SessionLocal
from app.messaging.metric_consumer import process_metric_event
from app.services.alerting import evaluate_metric
from tests.conftest import T0, internal_headers


@pytest.fixture
def client(apps):
    return TestClient(apps["metrics"], raise_server_exceptions=False)


def sample(i, name, value, service="svc", secs_ago=10):
    ts = (utcnow() - timedelta(seconds=secs_ago)).isoformat()
    process_metric_event({"event_id": f"{service}-{name}-{i}", "event_type": "metric", "service_name": service,
                          "timestamp": ts, "trace_id": f"tr{i}",
                          "payload": {"metric_name": name, "metric_value": value}})


def load():
    for i, (d, e) in enumerate([(100, 0), (200, 0), (300, 1), (400, 1)]):
        sample(i, "request_duration_ms", d)
        sample(i, "request_error", e)


def test_service_summary_latency_endpoints(client):
    load()
    h = internal_headers("viewer")
    svc = client.get("/api/v1/metrics/services?minutes=5", headers=h).json()["items"][0]
    assert svc["request_count"] == 4 and svc["error_count"] == 2 and svc["error_rate_percent"] == 50.0
    assert svc["average_latency_ms"] == 250 and svc["p95_latency_ms"] == 400 and svc["p50_latency_ms"] == 200
    summ = client.get("/api/v1/metrics/summary?minutes=5", headers=h).json()
    assert summ["request_count"] == 4 and summ["services_reporting"] == 1 and "nearest-rank" in summ["percentile_method"]
    lat = client.get("/api/v1/metrics/latency?minutes=5&service_name=svc", headers=h).json()["items"][0]
    assert (lat["minimum"], lat["maximum"], lat["p99"]) == (100, 400, 400)


def test_timeseries_validation_and_gaps(client):
    h = internal_headers("viewer")
    assert client.get("/api/v1/metrics/timeseries?metric=bogus", headers=h).status_code == 400
    assert client.get("/api/v1/metrics/timeseries?metric=request_count&bucket_seconds=13", headers=h).status_code == 400
    assert client.get("/api/v1/metrics/timeseries?metric=p95_latency", headers=h).status_code == 400
    load()
    client.post("/api/v1/alerts/evaluate", headers=internal_headers("admin"))     # aggregates the recent buckets
    series = client.get("/api/v1/metrics/timeseries?metric=request_count&service_name=svc", headers=h).json()
    assert sum(p["value"] or 0 for p in series["points"]) == 4 and series["missing_buckets"] > 0


def test_evaluate_creates_alerts_with_evidence_and_dedups(client):
    load()
    admin = internal_headers("admin")
    first = client.post("/api/v1/alerts/evaluate", headers=admin).json()
    assert first["alerts_created_or_updated"] >= 1
    alerts = client.get("/api/v1/alerts?status=active", headers=admin).json()
    err = next(a for a in alerts["items"] if a["alert_type"] == "error_rate_percent")
    assert err["measured_value"] == 50.0 and err["threshold_value"] == 20.0 and err["trace_ids"]
    client.post("/api/v1/alerts/evaluate", headers=admin)    # again: no duplicate alerts
    assert client.get("/api/v1/alerts", headers=admin).json()["total"] == alerts["total"]


def test_alert_get_patch_and_transitions(client):
    with SessionLocal() as db:
        alert = evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0)
        alert_id = alert.id
    analyst, viewer = internal_headers("analyst"), internal_headers("viewer")
    assert client.get(f"/api/v1/alerts/{alert_id}", headers=viewer).json()["status"] == "active"
    assert client.get("/api/v1/alerts/999", headers=viewer).status_code == 404
    assert client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "acknowledged"}, headers=viewer).status_code == 403
    r = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "acknowledged"}, headers=analyst)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["acknowledged_at"]
    assert client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "acknowledged"}, headers=analyst).status_code == 200
    assert client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "resolved"}, headers=analyst).json()["resolved_at"]
    assert client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "acknowledged"}, headers=analyst).status_code == 409
    assert client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "bogus"}, headers=analyst).status_code == 422


def test_alert_rules_are_configurable_by_admin_only(client):
    body = {"alert_type": "avg_latency_ms", "service_name": "svc", "threshold_value": 50}
    assert client.put("/api/v1/alerts/rules", json=body, headers=internal_headers("analyst")).status_code == 403
    assert client.put("/api/v1/alerts/rules", json=body, headers=internal_headers("admin")).status_code == 200
    rules = client.get("/api/v1/alerts/rules", headers=internal_headers("viewer")).json()
    assert rules["overrides"][0]["threshold_value"] == 50 and len(rules["defaults"]) == 4


def test_admin_endpoints_need_admin(client):
    assert client.post("/api/v1/alerts/evaluate", headers=internal_headers("analyst")).status_code == 403
    body = {"interval_start": "2026-01-02T00:00:00", "interval_end": "2026-01-01T00:00:00"}
    assert client.post("/api/v1/metrics/aggregate", json=body, headers=internal_headers("admin")).status_code == 422
    ok = {"interval_start": "2026-01-01T00:00:00", "interval_end": "2026-01-01T00:01:00"}
    assert client.post("/api/v1/metrics/aggregate", json=ok, headers=internal_headers("admin")).status_code == 200
