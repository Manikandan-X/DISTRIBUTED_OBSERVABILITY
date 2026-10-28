"""One-call instrumentation for a FastAPI service.

``setup_service_telemetry(app, "payment-service")`` wires up
* OpenTelemetry tracing (FastAPI + httpx) -> Ingestion Service
* structured logs (WARNING+ always, INFO too) -> Ingestion Service, tagged
  with trace_id / span_id / correlation_id
* request metrics (``request_duration_ms``, ``request_error``) per request
"""

import logging
import time

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import settings
from app.core.context import get_correlation_id
from app.telemetry.client import get_telemetry_client
from app.telemetry.otel_exporter import IngestionSpanExporter

EXCLUDED_URLS = "health,ready,docs,openapi.json"
_NOISY_LOGGERS = ("app.telemetry", "httpx", "httpcore", "uvicorn.access")


class TelemetryLogHandler(logging.Handler):
    """Ship application log records to the ingestion service."""

    def __init__(self, service_name: str):
        super().__init__(level=logging.INFO)
        self.client = get_telemetry_client(service_name)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_NOISY_LOGGERS):
            return
        try:
            ctx = trace.get_current_span().get_span_context()
            payload = {"message": record.getMessage()[:5000], "severity": record.levelname}
            trace_id = None
            if ctx.is_valid:
                trace_id = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")
            self.client.emit("log", payload, trace_id=trace_id, correlation_id=get_correlation_id())
        except Exception:  # logging must never raise
            self.handleError(record)


class MetricsMiddleware:
    """Emit one duration sample and one error flag per HTTP request."""

    def __init__(self, app, service_name: str):
        self.app = app
        self.client = get_telemetry_client(service_name)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or any(x in scope.get("path", "") for x in ("/health", "/ready")):
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status_code = 500

        async def capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            ctx = trace.get_current_span().get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
            cid = get_correlation_id()
            self.client.emit("metric", {"metric_name": "request_duration_ms",
                                        "metric_value": round((time.perf_counter() - started) * 1000, 3),
                                        "unit": "ms"}, trace_id=trace_id, correlation_id=cid)
            self.client.emit("metric", {"metric_name": "request_error",
                                        "metric_value": 1.0 if status_code >= 500 else 0.0},
                             trace_id=trace_id, correlation_id=cid)


def setup_service_telemetry(app: FastAPI, service_name: str) -> None:
    if not settings.telemetry_enabled:
        return
    client = get_telemetry_client(service_name)

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(IngestionSpanExporter(client), schedule_delay_millis=1000))
    trace.set_tracer_provider(provider)

    logging.getLogger().addHandler(TelemetryLogHandler(service_name))
    app.add_middleware(MetricsMiddleware, service_name=service_name)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS,
                                       exclude_spans=["send", "receive"])
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
