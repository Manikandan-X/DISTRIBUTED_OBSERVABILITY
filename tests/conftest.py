"""Shared fixtures.

The whole suite runs on in-memory SQLite and in-process ASGI transports, so it
needs neither MySQL nor RabbitMQ. Service-to-service HTTP calls are routed to
the other FastAPI apps through ``httpx.MockTransport`` (see ``wire``).
"""

import os

os.environ.update({
    "DATABASE_URL": "sqlite://",
    "INTERNAL_API_TOKEN": "test-internal-token",
    "INGESTION_API_KEYS": "test-key,other-key",
    "INGESTION_API_KEY": "test-key",
    "JWT_SECRET": "test-secret-test-secret-test-secret",
    "CONSOLE_ADMIN_PASSWORD": "admin-pw",
    "CONSOLE_ANALYST_PASSWORD": "analyst-pw",
    "CONSOLE_VIEWER_PASSWORD": "viewer-pw",
    "TELEMETRY_ENABLED": "false",
    "BACKGROUND_WORKERS_ENABLED": "false",
    "DOWNSTREAM_MAX_ATTEMPTS": "2",
    "DOWNSTREAM_BACKOFF_SECONDS": "0",
    "BROKER_PUBLISH_ATTEMPTS": "2",
    "BROKER_PUBLISH_BACKOFF_SECONDS": "0",
    "SLOW_PAYMENT_SECONDS": "0.01",
    "NOTIFICATION_TIMEOUT_SECONDS": "0.01",
    "ALERT_MIN_SAMPLES": "3",
})

from datetime import datetime, timedelta  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.db.base  # noqa: E402,F401
from app.core import http_client  # noqa: E402
from app.db.session import Base, engine  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal-token"}


def internal_headers(role: str = "admin") -> dict:
    return {**INTERNAL, "X-User-Role": role}


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    http_client.TRANSPORT_OVERRIDES.clear()


@pytest.fixture
def apps():
    from app.apps.ingestion import app as ingestion
    from app.apps.log_service import app as log
    from app.apps.metrics_service import app as metrics
    from app.apps.query_service import app as query
    from app.apps.rca_service import app as rca
    from app.apps.trace_service import app as trace

    return {"ingestion": ingestion, "log": log, "metrics": metrics, "query": query, "rca": rca, "trace": trace}


def _asgi_transport(app) -> httpx.MockTransport:
    client = TestClient(app, raise_server_exceptions=False)

    def handler(request: httpx.Request) -> httpx.Response:
        response = client.request(request.method, str(request.url.raw_path, "ascii"),
                                  content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    return httpx.MockTransport(handler)


@pytest.fixture
def wire(apps):
    """Route service-to-service calls to the in-process apps."""
    def _wire(**overrides):
        for name, app in apps.items():
            http_client.TRANSPORT_OVERRIDES[name] = _asgi_transport(app)
        for name, transport in overrides.items():
            http_client.TRANSPORT_OVERRIDES[name] = transport
    _wire()
    return _wire


def failing_transport(kind: str = "connect") -> httpx.MockTransport:
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if kind == "500":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        raise httpx.ConnectError("refused", request=request)
    return httpx.MockTransport(handler)


@pytest.fixture
def inline_broker(monkeypatch):
    """Replace RabbitMQ: published events are processed by the consumers inline."""
    from app.messaging import publisher, log_consumer, metric_consumer, trace_consumer

    handlers = {"trace": trace_consumer.process_trace_event, "log": log_consumer.process_log_event,
                "metric": metric_consumer.process_metric_event}
    published: list[dict] = []

    def fake_publish(events):
        for event in events:
            published.append(event)
            handlers[event["event_type"]](event)

    monkeypatch.setattr(publisher, "publish_batch", fake_publish)
    return published


T0 = datetime(2026, 1, 1, 12, 0, 0)


def span_event(trace_id, span_id, parent, service, start_ms, end_ms, status="ok", error=None, op=None,
               correlation_id=None):
    return {
        "event_id": f"ev-{trace_id}-{span_id}", "event_type": "trace", "service_name": service,
        "trace_id": trace_id, "correlation_id": correlation_id,
        "timestamp": (T0 + timedelta(milliseconds=end_ms)).isoformat(),
        "payload": {"span_id": span_id, "parent_span_id": parent, "operation_name": op or f"{service}.op",
                    "start_time": (T0 + timedelta(milliseconds=start_ms)).isoformat(),
                    "end_time": (T0 + timedelta(milliseconds=end_ms)).isoformat(),
                    "status": status, "error_message": error},
    }


def log_event(event_id, service, severity, message, trace_id=None, span_id=None, ts=None):
    event = {"event_id": event_id, "event_type": "log", "service_name": service,
             "timestamp": (ts or T0).isoformat(), "payload": {"severity": severity, "message": message}}
    if trace_id:
        event["trace_id"] = trace_id
    if span_id:
        event["payload"]["span_id"] = span_id
    return event


def failing_trace(trace_id="t-fail"):
    """gateway -> order -> payment (fails) -> notification (never reached)."""
    return [
        span_event(trace_id, "a1", None, "api-gateway", 0, 120, "error", "HTTP 502"),
        span_event(trace_id, "b1", "a1", "order-service", 10, 115, "error", "Payment service failed"),
        span_event(trace_id, "c1", "b1", "payment-service", 20, 100, "error", "Payment provider rejected the transaction"),
    ]
