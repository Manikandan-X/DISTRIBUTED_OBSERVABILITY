import pytest
from fastapi.testclient import TestClient

from app.messaging.log_consumer import process_log_event
from app.messaging.trace_consumer import process_trace_event
from tests.conftest import INTERNAL, failing_trace, log_event, span_event


@pytest.fixture
def trace_client(apps):
    return TestClient(apps["trace"], raise_server_exceptions=False)


@pytest.fixture
def log_client(apps):
    return TestClient(apps["log"], raise_server_exceptions=False)


@pytest.fixture
def seeded():
    for e in failing_trace("t-fail"):
        process_trace_event(e)
    for e in [span_event("t-ok", "r", None, "api-gateway", 0, 30, correlation_id="corr-1"),
              span_event("t-ok", "o", "r", "order-service", 5, 25)]:
        process_trace_event(e)
    process_log_event(log_event("l1", "payment-service", "ERROR", "Payment 17 declined", "t-fail", "c1"))
    process_log_event(log_event("l2", "payment-service", "ERROR", "Payment 18 declined", "t-fail", "c1"))
    process_log_event(log_event("l3", "order-service", "INFO", "order ok", "t-ok"))


def test_internal_endpoints_require_token(trace_client, log_client):
    assert trace_client.get("/api/v1/traces").status_code == 401
    assert log_client.get("/api/v1/logs").status_code == 401


def test_trace_list_filters_and_pagination(trace_client, seeded):
    h = INTERNAL
    assert trace_client.get("/api/v1/traces", headers=h).json()["total"] == 2
    assert trace_client.get("/api/v1/traces?status=error", headers=h).json()["total"] == 1
    assert trace_client.get("/api/v1/traces?correlation_id=corr-1", headers=h).json()["items"][0]["trace_id"] == "t-ok"
    assert trace_client.get("/api/v1/traces?trace_id=t-fail", headers=h).json()["total"] == 1
    page = trace_client.get("/api/v1/traces?limit=1&offset=1", headers=h).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["offset"] == 1
    assert trace_client.get("/api/v1/traces?limit=0", headers=h).status_code == 422


def test_invalid_time_range_is_rejected(trace_client, log_client):
    q = "start_time=2026-01-02T00:00:00&end_time=2026-01-01T00:00:00"
    assert trace_client.get(f"/api/v1/traces?{q}", headers=INTERNAL).status_code == 400
    assert log_client.get(f"/api/v1/logs?{q}", headers=INTERNAL).status_code == 400


def test_unknown_and_malformed_trace_ids(trace_client, seeded):
    r = trace_client.get("/api/v1/traces/nope", headers=INTERNAL)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert trace_client.get("/api/v1/traces/bad%20id!", headers=INTERNAL).status_code == 422
    assert trace_client.get("/api/v1/traces/nope/spans", headers=INTERNAL).status_code == 404


def test_trace_detail_reconstructs_timeline(trace_client, seeded):
    d = trace_client.get("/api/v1/traces/t-fail", headers=INTERNAL).json()
    assert d["request_path"] == ["api-gateway", "order-service", "payment-service"]
    assert d["failed_span_ids"] == ["a1", "b1", "c1"] and d["is_complete"]
    assert [s["depth"] for s in d["spans"]] == [0, 1, 2]
    assert d["service_latency"][0]["service_name"] == "payment-service"


def test_incomplete_trace_is_flagged_with_missing_span(trace_client):
    process_trace_event(span_event("t-inc", "c", "gone", "payment-service", 0, 10))
    d = trace_client.get("/api/v1/traces/t-inc", headers=INTERNAL).json()
    assert not d["is_complete"] and d["missing_parent_span_ids"] == ["gone"]
    assert d["spans"][0]["is_orphan"] and any("incomplete" in w for w in d["warnings"])


def test_spans_endpoint_marks_slow_and_failed(trace_client, seeded, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "slow_span_threshold_ms", 100)
    spans = trace_client.get("/api/v1/traces/t-fail/spans", headers=INTERNAL).json()
    assert [s["is_failed"] for s in spans] == [True, True, True]
    assert [s["is_slow"] for s in spans] == [True, True, False]


def test_dependency_graph_is_derived_from_spans(trace_client, seeded):
    g = trace_client.get("/api/v1/dependencies", headers=INTERNAL).json()
    edges = {(e["source"], e["target"]): e for e in g["edges"]}
    assert set(edges) == {("api-gateway", "order-service"), ("order-service", "payment-service")}
    assert edges[("order-service", "payment-service")]["error_count"] == 1
    assert edges[("api-gateway", "order-service")]["request_count"] == 2
    failed = {(f["source"], f["target"]) for f in g["failure_relationships"]}
    assert failed == {("api-gateway", "order-service"), ("order-service", "payment-service")}
    node = {n["service_name"]: n for n in g["nodes"]}["payment-service"]
    assert node["error_rate_percent"] == 100.0


def test_service_dependency_detail_and_unknown_service(trace_client, seeded):
    d = trace_client.get("/api/v1/dependencies/order-service", headers=INTERNAL).json()
    assert [e["source"] for e in d["incoming"]] == ["api-gateway"]
    assert [e["target"] for e in d["outgoing"]] == ["payment-service"]
    assert trace_client.get("/api/v1/dependencies/ghost", headers=INTERNAL).status_code == 404


def test_trace_stats_use_nearest_rank(trace_client, seeded):
    s = trace_client.get("/api/v1/traces/stats/summary", headers=INTERNAL).json()
    assert s["total_requests"] == 2 and s["failed_requests"] == 1 and s["error_rate_percent"] == 50.0
    assert s["p95_latency_ms"] == 120.0 and s["services_reporting_errors"] == 3
    svc = {i["service_name"]: i for i in trace_client.get("/api/v1/traces/stats/services", headers=INTERNAL).json()["items"]}
    assert svc["payment-service"]["error_rate_percent"] == 100.0


# ---------------------------------------------------------------------- logs
def test_log_filters(log_client, seeded):
    h = INTERNAL
    assert log_client.get("/api/v1/logs", headers=h).json()["total"] == 3
    assert log_client.get("/api/v1/logs?severity=error", headers=h).json()["total"] == 2   # case-insensitive
    assert log_client.get("/api/v1/logs?service_name=order-service", headers=h).json()["total"] == 1
    assert log_client.get("/api/v1/logs?trace_id=t-fail&span_id=c1", headers=h).json()["total"] == 2
    assert log_client.get("/api/v1/logs?search=declined", headers=h).json()["total"] == 2
    assert log_client.get("/api/v1/logs?limit=1", headers=h).json()["items"].__len__() == 1


def test_log_filter_input_is_sanitised(log_client, seeded):
    assert log_client.get("/api/v1/logs?severity=LOUD", headers=INTERNAL).status_code == 422
    assert log_client.get("/api/v1/logs?search=%25", headers=INTERNAL).json()["total"] == 0   # '%' is literal
    assert log_client.get("/api/v1/logs?search=x'%20OR%201=1--", headers=INTERNAL).json()["total"] == 0


def test_log_by_correlation_id(log_client):
    ev = log_event("c1", "svc", "INFO", "hello")
    ev["correlation_id"] = "corr-77"
    process_log_event(ev)
    assert log_client.get("/api/v1/logs?correlation_id=corr-77", headers=INTERNAL).json()["total"] == 1


def test_get_log_and_trace_logs(log_client, seeded):
    first = log_client.get("/api/v1/logs?limit=1", headers=INTERNAL).json()["items"][0]
    assert log_client.get(f"/api/v1/logs/{first['id']}", headers=INTERNAL).json()["event_id"] == first["event_id"]
    assert log_client.get("/api/v1/logs/9999", headers=INTERNAL).status_code == 404
    tl = log_client.get("/api/v1/traces/t-fail/logs", headers=INTERNAL).json()
    assert tl["total"] == 2 and all(i["trace_id"] == "t-fail" for i in tl["items"])


def test_repeated_error_patterns_are_grouped(log_client, seeded):
    p = log_client.get("/api/v1/logs/patterns", headers=INTERNAL).json()
    assert p["total"] == 1
    item = p["items"][0]
    assert item["occurrence_count"] == 2 and item["service_name"] == "payment-service"
    assert item["example_trace_ids"] == ["t-fail"]
