import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.messaging import publisher
from app.messaging.publisher import BrokerUnavailableError
from app.models.ingestion_event import IngestionEvent
from app.services.ingestion import relay_failed_events
from tests.conftest import INTERNAL, internal_headers, log_event, span_event

KEY = {"X-API-Key": "test-key"}


@pytest.fixture
def client(apps):
    return TestClient(apps["ingestion"], raise_server_exceptions=False)


def test_requires_api_key(client):
    r = client.post("/api/v1/telemetry/logs", json={"events": [log_event("e1", "svc", "INFO", "hi")]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert client.post("/api/v1/telemetry/logs", headers={"X-API-Key": "wrong"}, json={"events": []}).status_code == 401


def test_valid_log_batch_is_accepted_and_published(client, inline_broker):
    events = [log_event("l1", "Payment Service", "warn", "slow"), log_event("l2", "payment-service", "ERROR", "boom")]
    r = client.post("/api/v1/telemetry/logs", headers=KEY, json={"events": events})
    assert r.status_code == 202
    body = r.json()
    assert (body["accepted"], body["rejected"], body["duplicates"]) == (2, 0, 0)
    assert [e["service_name"] for e in inline_broker] == ["payment-service"] * 2        # normalised
    assert inline_broker[0]["payload"]["severity"] == "WARNING"                           # normalised


def test_malformed_events_are_rejected_individually_and_never_published(client, inline_broker):
    events = [log_event("ok1", "svc", "INFO", "fine"),
              log_event("bad1", "svc", "LOUD", "x"),                 # unknown severity
              {"event_id": "bad2", "event_type": "trace", "service_name": "svc", "payload": {}},  # no trace_id
              "not-an-object",
              {"event_id": "bad3", "event_type": "metric", "service_name": "svc",
               "payload": {"metric_name": "m", "metric_value": "NaN"}}]
    r = client.post("/api/v1/telemetry/batch", headers=KEY, json={"events": events})
    body = r.json()
    assert r.status_code == 202 and body["accepted"] == 1 and body["rejected"] == 4
    assert [e["event_id"] for e in inline_broker] == ["ok1"]
    reasons = {x["index"]: " ".join(x["errors"]) for x in body["rejections"]}
    assert "severity" in reasons[1] and "trace_id" in reasons[2] and "JSON object" in reasons[3]


def test_all_invalid_batch_is_422_with_meaningful_message(client, inline_broker):
    r = client.post("/api/v1/telemetry/traces", headers=KEY, json={"events": [{"event_type": "trace"}]})
    assert r.status_code == 422 and "rejected" in r.json()["error"]["message"].lower()
    assert inline_broker == []


def test_endpoint_enforces_event_type(client, inline_broker):
    r = client.post("/api/v1/telemetry/metrics", headers=KEY, json={"events": [log_event("x", "svc", "INFO", "m")]})
    assert r.status_code == 422 and "event_type must be 'metric'" in r.text


def test_duplicate_event_ids_are_idempotent(client, inline_broker):
    payload = {"events": [log_event("same", "svc", "INFO", "once")]}
    client.post("/api/v1/telemetry/logs", headers=KEY, json=payload)
    r = client.post("/api/v1/telemetry/logs", headers=KEY, json=payload)
    assert r.status_code == 202 and r.json()["duplicates"] == 1 and r.json()["accepted"] == 0
    assert len(inline_broker) == 1


def test_trace_ids_span_ids_and_correlation_ids_are_preserved(client, inline_broker):
    ev = span_event("abc123", "s1", None, "svc", 0, 10, correlation_id="corr-9")
    client.post("/api/v1/telemetry/traces", headers=KEY, json={"events": [ev]})
    sent = inline_broker[0]
    assert sent["trace_id"] == "abc123" and sent["payload"]["span_id"] == "s1" and sent["correlation_id"] == "corr-9"


def test_timestamps_are_normalised_to_utc(client, inline_broker):
    ev = log_event("tz", "svc", "INFO", "x")
    ev["timestamp"] = "2026-01-01T14:00:00+02:00"
    client.post("/api/v1/telemetry/logs", headers=KEY, json={"events": [ev]})
    assert inline_broker[0]["timestamp"] == "2026-01-01T12:00:00"


def test_request_body_and_batch_size_limits(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_request_bytes", 500)
    big = {"events": [log_event("big", "svc", "INFO", "x" * 2000)]}
    assert client.post("/api/v1/telemetry/logs", headers=KEY, json=big).status_code == 413
    monkeypatch.setattr(settings, "max_request_bytes", 1_000_000)
    monkeypatch.setattr(settings, "max_batch_events", 2)
    many = {"events": [log_event(f"e{i}", "svc", "INFO", "x") for i in range(3)]}
    assert client.post("/api/v1/telemetry/logs", headers=KEY, json=many).status_code == 413


def test_validation_errors_do_not_echo_secrets(client):
    r = client.post("/api/v1/telemetry/batch", headers=KEY, json={"events": "password=hunter2"})
    assert r.status_code == 422 and "hunter2" not in r.text


# ------------------------------------------------------------- broker down
def _broker_down(events):
    raise BrokerUnavailableError("down")


def test_broker_outage_keeps_event_and_relay_republishes(client, monkeypatch):
    monkeypatch.setattr(publisher, "publish_batch", _broker_down)
    r = client.post("/api/v1/telemetry/logs", headers=KEY, json={"events": [log_event("q1", "svc", "INFO", "kept")]})
    assert r.status_code == 202 and r.json()["queued_for_retry"] == 1
    with SessionLocal() as db:
        row = db.query(IngestionEvent).one()
        assert row.processing_status == "publish_failed" and row.raw_event["payload"]["message"] == "kept"

    sent = []
    monkeypatch.setattr(publisher, "publish_batch", lambda events: sent.extend(events))   # broker is back
    with SessionLocal() as db:
        assert relay_failed_events(db) == 1
        assert db.query(IngestionEvent).one().processing_status == "published"
    assert sent[0]["event_id"] == "q1"


def test_legacy_single_event_endpoint_status_codes(client, inline_broker, monkeypatch):
    ev = log_event("legacy", "svc", "INFO", "x")
    assert client.post("/api/v1/telemetry", headers=KEY, json=ev).status_code == 201
    assert client.post("/api/v1/telemetry", headers=KEY, json=ev).status_code == 409
    monkeypatch.setattr(publisher, "publish_batch", _broker_down)
    assert client.post("/api/v1/telemetry", headers=KEY, json=log_event("l2", "svc", "INFO", "y")).status_code == 503


def test_publish_batch_retries_are_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(publisher, "_publish_once", lambda e: calls.append(1) or (_ for _ in ()).throw(BrokerUnavailableError("x")))
    with pytest.raises(BrokerUnavailableError):
        publisher.publish_batch([log_event("e", "svc", "INFO", "m")])
    assert len(calls) == 2  # BROKER_PUBLISH_ATTEMPTS=2


def test_statistics_and_admin_endpoints_are_protected(client, inline_broker):
    client.post("/api/v1/telemetry/logs", headers=KEY, json={"events": [log_event("s1", "svc", "INFO", "x")]})
    assert client.get("/api/v1/telemetry/stats").status_code == 401
    stats = client.get("/api/v1/telemetry/stats", headers=INTERNAL).json()
    assert stats["totals"]["published"] == 1 and stats["publish_success_rate_percent"] == 100.0
    assert client.post("/api/v1/telemetry/retry-failed").status_code == 401
    assert client.post("/api/v1/telemetry/retry-failed", headers=internal_headers()).json() == {"republished": 0}
