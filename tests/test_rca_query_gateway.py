import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.http_client import DownstreamClient, DownstreamError
from app.messaging.log_consumer import process_log_event
from app.messaging.metric_consumer import process_metric_event
from app.messaging.trace_consumer import process_trace_event
from tests.conftest import failing_trace, failing_transport, internal_headers, log_event, span_event


@pytest.fixture
def rca(apps):
    return TestClient(apps["rca"], raise_server_exceptions=False)


@pytest.fixture
def query(apps):
    return TestClient(apps["query"], raise_server_exceptions=False)


@pytest.fixture
def seeded():
    for e in failing_trace("t-fail"):
        process_trace_event(e)
    process_log_event(log_event("l1", "payment-service", "ERROR", "Card declined by provider", "t-fail", "c1"))
    process_log_event(log_event("l2", "order-service", "INFO", "Order created", "t-fail", "b1"))


A, V = internal_headers("analyst"), internal_headers("viewer")


# ------------------------------------------------------------------- RCA
def test_analyze_failed_trace_produces_evidence_based_report(rca, wire, seeded):
    r = rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A)
    assert r.status_code == 201
    rep = r.json()
    assert rep["affected_service"] == "payment-service" and rep["root_cause_status"] == "confirmed"
    assert rep["severity"] == "HIGH" and rep["confidence_level"] >= 0.8
    ev = rep["evidence"]
    assert ev["first_failing_span_id"] == "c1" and ev["request_path"] == ["api-gateway", "order-service", "payment-service"]
    assert ev["ranked_services"][0]["service_name"] == "payment-service"
    assert {l["service_name"] for l in ev["latency_contribution"]} == {"api-gateway", "order-service", "payment-service"}
    types = {i["evidence_type"] for i in rep["evidence_items"]}
    assert {"trace_span", "log", "latency"} <= types
    log_item = next(i for i in rep["evidence_items"] if i["evidence_type"] == "log")
    assert log_item["reference_id"] == "l1" and "Card declined" in log_item["description"]


def test_unknown_trace_is_404_and_viewer_is_forbidden(rca, wire, seeded):
    assert rca.post("/api/v1/diagnostics/analyze/ghost", headers=A).status_code == 404
    assert rca.post("/api/v1/diagnostics/analyze/t-fail", headers=V).status_code == 403
    assert rca.get("/api/v1/diagnostics").status_code == 401


def test_log_service_outage_degrades_to_warning_not_failure(rca, wire, seeded):
    wire(log=failing_transport("connect"))
    rep = rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A).json()
    assert any("Log service unavailable" in w for w in rep["warnings"])
    assert rep["affected_service"] == "payment-service"


def test_trace_service_outage_fails_instead_of_guessing(rca, wire, seeded):
    wire(trace=failing_transport("timeout"))
    r = rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A)
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"


def test_incomplete_trace_is_not_claimed_as_confirmed(rca, wire):
    process_trace_event(span_event("t-inc", "c", "lost-parent", "payment-service", 0, 50, "error", "boom"))
    rep = rca.post("/api/v1/diagnostics/analyze/t-inc", headers=A).json()
    assert rep["root_cause_status"] == "probable" and rep["confidence_level"] <= 0.6
    assert any("incomplete" in l.lower() for l in rep["evidence"]["limitations"])


def test_metric_and_alert_evidence_is_attached(rca, wire, seeded):
    from app.core.timeutils import utcnow
    for i in range(6):
        for name, val in (("request_duration_ms", 100), ("request_error", 1)):
            process_metric_event({"event_id": f"m{i}{name}", "event_type": "metric", "service_name": "payment-service",
                                  "timestamp": utcnow().isoformat(), "trace_id": "t-fail",
                                  "payload": {"metric_name": name, "metric_value": val}})
    rep = rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A).json()
    metric = next(i for i in rep["evidence_items"] if i["evidence_type"] == "metric")
    assert "error_rate_percent=100" in metric["description"]


def test_list_and_get_reports(rca, wire, seeded):
    first = rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A).json()
    rca.post("/api/v1/diagnostics/traces/t-fail/analyze", headers=A)          # legacy alias
    listing = rca.get("/api/v1/diagnostics?trace_id=t-fail&limit=1", headers=A).json()
    assert listing["total"] == 2 and len(listing["items"]) == 1
    assert rca.get("/api/v1/diagnostics?severity=HIGH&root_cause_status=confirmed", headers=A).json()["total"] == 2
    assert rca.get(f"/api/v1/diagnostics/{first['id']}", headers=A).json()["id"] == first["id"]
    assert rca.get("/api/v1/diagnostics/999", headers=A).status_code == 404
    assert rca.get("/api/v1/diagnostics?severity=BAD", headers=A).status_code == 422


# ----------------------------------------------------------------- query
def test_query_trace_composes_trace_logs_and_reports(query, rca, wire, seeded):
    rca.post("/api/v1/diagnostics/analyze/t-fail", headers=A)
    d = query.get("/api/v1/traces/t-fail", headers=A).json()
    assert d["partial"] is False and len(d["logs"]) == 2
    assert not any("unavailable" in w for w in d["warnings"])
    assert d["diagnostic_reports"][0]["affected_service"] == "payment-service"
    assert d["failed_span_ids"] == ["a1", "b1", "c1"]


def test_query_returns_partial_results_with_warning_when_rca_is_down(query, wire, seeded):
    wire(rca=failing_transport("connect"))
    d = query.get("/api/v1/traces/t-fail", headers=A).json()
    assert d["partial"] is True and len(d["spans"]) == 3 and len(d["logs"]) == 2
    assert any("rca-service" in w for w in d["warnings"]) and d["diagnostic_reports"] == []


def test_query_partial_when_logs_down_and_hidden_from_viewers(query, wire, seeded):
    wire(log=failing_transport("timeout"))
    d = query.get("/api/v1/traces/t-fail", headers=A).json()
    assert d["partial"] and any("log-service" in w for w in d["warnings"])
    viewer = query.get("/api/v1/traces/t-fail", headers=V).json()
    assert viewer["logs"] == [] and viewer["diagnostic_reports"] == [] and any("analyst" in w for w in viewer["warnings"])


def test_query_trace_failure_is_an_explicit_error(query, wire, seeded):
    assert query.get("/api/v1/traces/ghost", headers=A).status_code == 404
    wire(trace=failing_transport("timeout"))
    r = query.get("/api/v1/traces/t-fail", headers=A)
    assert r.status_code == 504 and r.json()["error"]["source"] == "trace-service"


def test_query_access_control_for_logs_and_diagnostics(query, wire, seeded):
    assert query.get("/api/v1/logs", headers=V).status_code == 403
    assert query.get("/api/v1/diagnostics", headers=V).status_code == 403
    assert query.get("/api/v1/logs", headers=A).status_code == 200
    assert query.get("/api/v1/traces").status_code == 401


def test_overview_is_partial_when_metrics_service_is_down(query, wire, seeded):
    ok = query.get("/api/v1/overview", headers=V).json()
    assert ok["total_requests"] == 1 and ok["error_rate_percent"] == 100.0 and ok["partial"] is False
    wire(metrics=failing_transport("500"))
    degraded = query.get("/api/v1/overview", headers=V).json()
    assert degraded["partial"] and degraded["total_requests"] == 1 and any("Metrics" in w for w in degraded["warnings"])
    wire(metrics=failing_transport("500"), trace=failing_transport("500"))
    assert query.get("/api/v1/overview", headers=V).status_code in (502, 503)


def test_query_forwards_filters_and_validates_ranges(query, wire, seeded):
    assert query.get("/api/v1/traces?service_name=api-gateway&limit=1", headers=V).json()["total"] == 1
    bad = "start_time=2026-01-02T00:00:00&end_time=2026-01-01T00:00:00"
    assert query.get(f"/api/v1/traces?{bad}", headers=V).status_code == 400
    assert query.get("/api/v1/dependencies/order-service", headers=V).status_code == 200
    assert query.get("/api/v1/dependencies/ghost", headers=V).status_code == 404


# ----------------------------------------------------------------- gateway
@pytest.fixture
def gateway(apps, wire):
    from app.apps.gateway import app
    return TestClient(app, raise_server_exceptions=False)


def login(gateway, user, password):
    return gateway.post("/api/v1/auth/login", json={"username": user, "password": password})


def bearer(gateway, user="analyst", password="analyst-pw"):
    return {"Authorization": f"Bearer {login(gateway, user, password).json()['access_token']}"}


def test_login_success_and_failure(gateway):
    ok = login(gateway, "admin", "admin-pw").json()
    assert ok["role"] == "admin" and ok["token_type"] == "bearer"
    bad = login(gateway, "admin", "nope")
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    assert login(gateway, "ghost", "x").status_code == 401


def test_gateway_requires_authentication_and_roles(gateway, seeded):
    r = gateway.get("/api/v1/traces")
    assert r.status_code == 401 and r.headers["x-error-source"] == "gateway" and r.json()["error"]["source"] == "api-gateway"
    assert gateway.get("/api/v1/traces", headers={"Authorization": "Bearer garbage"}).status_code == 401
    viewer = bearer(gateway, "viewer", "viewer-pw")
    assert gateway.get("/api/v1/traces", headers=viewer).status_code == 200
    forbidden = gateway.get("/api/v1/diagnostics", headers=viewer)
    assert forbidden.status_code == 403 and forbidden.headers["x-error-source"] == "gateway"
    assert gateway.patch("/api/v1/alerts/1", json={"status": "resolved"}, headers=viewer).status_code == 403


def test_gateway_proxies_and_propagates_correlation_id(gateway, seeded):
    r = gateway.get("/api/v1/traces/t-fail", headers={**bearer(gateway), "X-Correlation-ID": "corr-abc"})
    assert r.status_code == 200 and r.headers["x-correlation-id"] == "corr-abc"
    assert r.json()["request_path"][0] == "api-gateway"
    assert gateway.get("/api/v1/traces").headers["x-correlation-id"]            # generated when absent


def test_gateway_failure_is_distinguishable_from_downstream_failure(gateway, wire, seeded):
    # downstream returns 404 -> passed through, marked as downstream
    r = gateway.get("/api/v1/traces/ghost", headers=bearer(gateway))
    assert r.status_code == 404 and r.headers["x-error-source"] == "downstream"
    # downstream timeout -> 504 attributed to the downstream service
    wire(query=failing_transport("timeout"))
    t = gateway.get("/api/v1/traces", headers=bearer(gateway))
    assert t.status_code == 504 and t.headers["x-error-source"] == "downstream"
    assert t.json()["error"]["code"] == "downstream_timeout" and t.json()["error"]["source"] == "query-service"
    # downstream unreachable -> 503
    wire(query=failing_transport("connect"))
    u = gateway.get("/api/v1/traces", headers=bearer(gateway))
    assert u.status_code == 503 and u.json()["error"]["code"] == "downstream_unavailable"


def test_gateway_unknown_route_method_and_size_limit(gateway, monkeypatch):
    h = bearer(gateway)
    assert gateway.get("/api/v1/unknown", headers=h).status_code == 404
    assert gateway.delete("/api/v1/traces", headers=h).status_code == 405
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_request_bytes", 100)
    big = gateway.post("/api/v1/telemetry/logs", content=b"x" * 500, headers={"X-API-Key": "test-key"})
    assert big.status_code == 413


def test_gateway_telemetry_route_uses_api_key_not_jwt(gateway, inline_broker):
    body = {"events": [log_event("gw1", "svc", "INFO", "via gateway")]}
    assert gateway.post("/api/v1/telemetry/logs", json=body).status_code == 401
    ok = gateway.post("/api/v1/telemetry/logs", json=body, headers={"X-API-Key": "test-key"})
    assert ok.status_code == 202 and ok.json()["accepted"] == 1


def test_gateway_forwards_role_so_downstream_enforces_it(gateway, wire, seeded):
    # analyst can analyse through the full gateway -> query -> rca chain
    r = gateway.post("/api/v1/diagnostics/analyze/t-fail", headers=bearer(gateway))
    assert r.status_code == 201 and r.json()["affected_service"] == "payment-service"


# ------------------------------------------------------------ http client
def test_downstream_client_retry_is_bounded_and_only_for_get(wire):
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={})

    wire(trace=httpx.MockTransport(handler))
    with pytest.raises(DownstreamError) as exc:
        DownstreamClient("trace").get("/x")
    assert exc.value.kind == "http_error" and calls == ["GET", "GET"]        # DOWNSTREAM_MAX_ATTEMPTS=2
    calls.clear()
    with pytest.raises(DownstreamError):
        DownstreamClient("trace").post("/x", {})
    assert calls == ["POST"]                                                  # never retry non-idempotent calls


def test_downstream_client_client_errors_not_retried_and_bad_json(wire):
    calls = []
    wire(trace=httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(404, json={"error": {"message": "nope"}})))
    with pytest.raises(DownstreamError) as exc:
        DownstreamClient("trace").get("/x")
    assert exc.value.status_code == 404 and exc.value.message == "nope" and len(calls) == 1
    wire(trace=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))
    with pytest.raises(DownstreamError) as exc:
        DownstreamClient("trace").get("/x")
    assert exc.value.kind == "bad_response"
