import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.timeutils import utcnow
from app.db.session import SessionLocal
from app.messaging.consumer_base import run_consumer
from app.models.trace import Trace
from app.models.trace_span import TraceSpan
from app.schemas.telemetry import TelemetryEventRequest
from app.schemas.trace import TraceSpanPayload

logger = logging.getLogger(__name__)

QUEUE_NAME = "trace.processing"
ROUTING_KEY = "telemetry.trace"


def calculate_duration_ms(start_time, end_time) -> float:
    return max(0.0, (end_time - start_time).total_seconds() * 1000)


def process_trace_event(event_data: dict) -> None:
    """Idempotently store one span and update its trace.

    * Duplicate deliveries of the same (trace_id, span_id) are ignored.
    * Spans may arrive in any order: the trace window and root service are
      recomputed from whatever has been received so far.
    * Original timestamps and parent ids are stored untouched.
    """
    event = TelemetryEventRequest.model_validate(event_data)
    if event.event_type != "trace":
        raise ValueError("Expected a trace event")
    if not event.trace_id:
        raise ValueError("Trace events must include trace_id")

    span_data = TraceSpanPayload.model_validate(event.payload)
    duration_ms = calculate_duration_ms(span_data.start_time, span_data.end_time)
    correlation_id = event.correlation_id or span_data.correlation_id
    now = utcnow()

    with SessionLocal() as db:
        if db.scalar(select(TraceSpan.id).where(
            TraceSpan.trace_id == event.trace_id, TraceSpan.span_id == span_data.span_id,
        )) is not None:
            logger.info("Span already processed: trace_id=%s span_id=%s", event.trace_id, span_data.span_id)
            return

        trace = db.scalar(select(Trace).where(Trace.trace_id == event.trace_id))
        if trace is None:
            trace = Trace(
                trace_id=event.trace_id, root_service=event.service_name,
                start_time=span_data.start_time, end_time=span_data.end_time,
                duration_ms=duration_ms, status=span_data.status, completed_at=None,
                correlation_id=correlation_id, span_count=1,
                completion_status="in_progress", last_span_received_at=now,
            )
            db.add(trace)
        else:
            if span_data.parent_span_id is None:
                trace.root_service = event.service_name
            trace.start_time = min(trace.start_time, span_data.start_time)
            trace.end_time = max(trace.end_time or span_data.end_time, span_data.end_time)
            trace.duration_ms = calculate_duration_ms(trace.start_time, trace.end_time)
            if span_data.status == "error":
                trace.status = "error"
            if correlation_id and not trace.correlation_id:
                trace.correlation_id = correlation_id
            trace.span_count = (trace.span_count or 0) + 1
            trace.last_span_received_at = now
            if trace.completion_status != "in_progress":  # late span: reopen
                trace.completion_status = "in_progress"
                trace.completed_at = None

        db.add(TraceSpan(
            trace_id=event.trace_id, span_id=span_data.span_id,
            parent_span_id=span_data.parent_span_id, service_name=event.service_name,
            operation_name=span_data.operation_name, start_time=span_data.start_time,
            end_time=span_data.end_time, duration_ms=duration_ms, status=span_data.status,
            error_message=span_data.error_message, correlation_id=correlation_id,
            attributes=span_data.attributes or None,
        ))

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.scalar(select(TraceSpan.id).where(
                TraceSpan.trace_id == event.trace_id, TraceSpan.span_id == span_data.span_id,
            )) is not None:
                logger.info("Concurrent duplicate span ignored: %s/%s", event.trace_id, span_data.span_id)
                return
            raise  # e.g. concurrent trace creation: let the retry policy handle it

    logger.info("Processed trace span: trace_id=%s span_id=%s duration_ms=%.3f",
                event.trace_id, span_data.span_id, duration_ms)


def main() -> None:
    settings.service_name = "trace-consumer"
    configure_logging()
    run_consumer(name="trace-consumer", queue=QUEUE_NAME, routing_key=ROUTING_KEY,
                 handler=process_trace_event)


if __name__ == "__main__":
    main()
