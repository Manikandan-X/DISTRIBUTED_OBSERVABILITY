"""OpenTelemetry span exporter that sends spans to the Ingestion Service."""

import logging
from datetime import datetime, timezone

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from app.schemas.trace import sanitize_attributes
from app.telemetry.client import TelemetryClient

logger = logging.getLogger("app.telemetry.exporter")


def _to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).replace(tzinfo=None)


# ASGI instrumentation creates an internal span for every response-body write
# ("... http send"). They are artifacts of a failure (the response carrying the
# 5xx), not where it started, so they are not exported.
NOISE_SUFFIXES = (" http send", " http receive")


def span_to_event(span: ReadableSpan, service_name: str) -> dict | None:
    ctx = span.context
    if ctx is None or not ctx.is_valid or span.end_time is None:
        return None
    if span.name.endswith(NOISE_SUFFIXES):
        return None
    trace_id, span_id = format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    parent = format(span.parent.span_id, "016x") if span.parent is not None and span.parent.is_valid else None

    attrs = dict(span.attributes or {})
    http_status = attrs.get("http.status_code") or attrs.get("http.response.status_code")
    is_error = span.status.status_code == StatusCode.ERROR or (isinstance(http_status, int) and http_status >= 500)

    error_message = None
    for event in span.events:
        if event.name == "exception":
            error_message = (event.attributes or {}).get("exception.message") or (event.attributes or {}).get("exception.type")
            if error_message:
                break
    if is_error and not error_message:
        error_message = span.status.description or (f"HTTP {http_status}" if http_status else "span ended with error status")

    start, end = _to_dt(span.start_time), _to_dt(span.end_time)
    return {
        "event_id": f"otel-{trace_id}-{span_id}",   # deterministic => retries are idempotent
        "event_type": "trace",
        "service_name": service_name,
        "trace_id": trace_id,
        "correlation_id": attrs.get("correlation.id"),
        "timestamp": end.isoformat(),
        "payload": {
            "span_id": span_id, "parent_span_id": parent, "operation_name": span.name[:255],
            "start_time": start.isoformat(), "end_time": end.isoformat(),
            "status": "error" if is_error else "ok",
            "error_message": str(error_message)[:2000] if error_message else None,
            "correlation_id": attrs.get("correlation.id"),
            "attributes": sanitize_attributes(attrs),
        },
    }


class IngestionSpanExporter(SpanExporter):
    def __init__(self, client: TelemetryClient):
        self.client = client

    def export(self, spans) -> SpanExportResult:
        for span in spans:
            try:
                service = (span.resource.attributes or {}).get("service.name", self.client.service_name)
                event = span_to_event(span, str(service))
                if event:
                    self.client.emit(
                        "trace", event["payload"], trace_id=event["trace_id"],
                        correlation_id=event["correlation_id"], event_id=event["event_id"],
                        timestamp=datetime.fromisoformat(event["timestamp"]))
            except Exception:
                logger.exception("Could not convert span for export")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self.client.stop()
