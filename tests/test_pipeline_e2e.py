"""End-to-end: real OpenTelemetry spans -> exporter -> ingestion API -> broker (inline)
-> consumers -> trace completion -> query -> root-cause analysis -> dependency graph."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

from app.core.timeutils import utcnow
from app.db.session import SessionLocal
from app.services.trace_completion import finalize_traces
from app.telemetry.otel_exporter import IngestionSpanExporter, span_to_event

A = {"X-Internal-Token": "test-internal-token", "X-User-Role": "analyst"}


class CapturingClient:
    service_name = "sample"

    def __init__(self):
        self.events = []

    def emit(self, event_type, payload, trace_id=None, correlation_id=None, event_id=None, timestamp=None):
        self.events.append({"event_id": event_id, "event_type": event_type, "service_name": "x", "trace_id": trace_id,
                            "correlation_id": correlation_id, "timestamp": timestamp.isoformat(), "payload": payload})

    def stop(self):
        pass


def make_spans(service_for_span):
    """gateway -> order -> payment (raises) -> notification (never called)."""
    captured = CapturingClient()
    providers = {}

    def tracer(service):
        if service not in providers:
            p = TracerProvider(resource=Resource.create({"service.name": service}))
            p.add_span_processor(SimpleSpanProcessor(IngestionSpanExporter(captured)))
            providers[service] = p
        return providers[service].get_tracer(service)

    with tracer("api-gateway").start_as_current_span("POST /orders") as g:
        g.set_attribute("correlation.id", "corr-e2e")
        g.set_attribute("password", "should-never-be-exported")
        with tracer("order-service").start_as_current_span("order.create"):
            with tracer("payment-service").start_as_current_span("payment.process") as p:
                p.record_exception(RuntimeError("Payment provider rejected the transaction"))
                p.set_status(Status(StatusCode.ERROR, "rejected"))
            trace.get_current_span().set_status(Status(StatusCode.ERROR, "payment failed"))
        g.set_status(Status(StatusCode.ERROR, "HTTP 502"))
    return captured.events


def test_exporter_converts_spans_and_never_exports_secrets():
    events = make_spans(None)
    assert len(events) == 3
    by_name = {e["payload"]["operation_name"]: e for e in events}
    pay = by_name["payment.process"]
    assert pay["payload"]["status"] == "error" and "rejected the transaction" in pay["payload"]["error_message"]
    assert pay["payload"]["parent_span_id"] == by_name["order.create"]["payload"]["span_id"]
    assert pay["trace_id"] == by_name["POST /orders"]["trace_id"] and len(pay["trace_id"]) == 32
    gw = by_name["POST /orders"]
    assert gw["correlation_id"] == "corr-e2e" and "password" not in gw["payload"]["attributes"]
    assert gw["event_id"].startswith("otel-")           # deterministic => retries are idempotent


def test_http_500_attribute_marks_span_failed(monkeypatch):
    class FakeSpan:
        name, start_time, end_time, events = "POST", 1_000_000_000, 2_000_000_000, []
        attributes = {"http.status_code": 500}
        status = Status(StatusCode.UNSET)
        parent = None
        context = type("C", (), {"is_valid": True, "trace_id": 1, "span_id": 2})()
    event = span_to_event(FakeSpan(), "svc")
    assert event["payload"]["status"] == "error" and event["payload"]["error_message"] == "HTTP 500"


def test_full_pipeline_from_spans_to_root_cause(apps, wire, inline_broker):
    events = make_spans(None)
    trace_id = events[0]["trace_id"]
    logs = [{"event_type": "log", "service_name": "payment-service", "trace_id": trace_id,
             "timestamp": utcnow().isoformat(), "correlation_id": "corr-e2e",
             "payload": {"severity": "ERROR", "message": "Payment provider rejected the transaction"}}]
    ingest = TestClient(apps["ingestion"])
    r = ingest.post("/api/v1/telemetry/batch", headers={"X-API-Key": "test-key"},
                    json={"events": [{**e, "service_name": e["payload"].get("svc", s)} for e, s in
                                     zip(events, ["payment-service", "order-service", "api-gateway"])] + logs})
    assert r.status_code == 202 and r.json()["rejected"] == 0 and r.json()["accepted"] == 4

    with SessionLocal() as db:
        finalize_traces(db, wait_seconds=0, now=utcnow() + timedelta(seconds=1))

    query = TestClient(apps["query"])
    found = query.get("/api/v1/traces?correlation_id=corr-e2e", headers=A).json()
    assert found["total"] == 1 and found["items"][0]["completion_status"] == "complete"

    detail = query.get(f"/api/v1/traces/{trace_id}", headers=A).json()
    assert detail["request_path"] == ["api-gateway", "order-service", "payment-service"]
    assert len(detail["spans"]) == 3 and len(detail["logs"]) == 1 and not detail["partial"]

    rep = query.post(f"/api/v1/diagnostics/analyze/{trace_id}", headers=A).json()
    assert rep["affected_service"] == "payment-service" and rep["root_cause_status"] == "confirmed"
    assert any(i["evidence_type"] == "log" for i in rep["evidence_items"])

    graph = query.get("/api/v1/dependencies", headers=A).json()
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("api-gateway", "order-service"), ("order-service", "payment-service")}
    assert query.get(f"/api/v1/traces/{trace_id}/logs", headers=A).json()["total"] == 1


def test_asgi_internal_send_spans_are_not_exported_and_origin_is_the_real_failure():
    """Regression: '<route> http send' spans carry the 5xx too and used to be picked as failure origins."""
    class Noise:
        name, start_time, end_time, events = "POST /orders http send", 1_000_000_000, 1_000_100_000, []
        attributes = {"http.status_code": 502}
        status = Status(StatusCode.ERROR)
        parent = None
        context = type("C", (), {"is_valid": True, "trace_id": 1, "span_id": 2})()
    assert span_to_event(Noise(), "order-service") is None

    from datetime import timedelta
    from app.services.rca_rules import DiagnosticRules, evaluate
    from app.services.trace_analysis import reconstruct_trace
    from tests.test_unit_trace_analysis import sp
    # sub-second ordering matters: payment fails first, then the callers fail
    spans = [sp("g", None, "api-gateway", 0, 419, "error"), sp("o", "g", "order-service", 10, 400, "error"),
             sp("p", "o", "payment-service", 20, 70, "error")]
    ev = evaluate(reconstruct_trace(spans), [], {}, [], DiagnosticRules())
    assert ev.affected_service == "payment-service" and ev.origin_span_ids == ["p"]
