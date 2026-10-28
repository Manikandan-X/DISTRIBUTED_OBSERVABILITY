import logging

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.messaging.consumer_base import run_consumer
from app.models.processed_log import ProcessedLog
from app.schemas.log import LogPayload
from app.schemas.telemetry import TelemetryEventRequest
from app.services.log_normalization import dedup_hash, message_fingerprint

logger = logging.getLogger(__name__)

QUEUE_NAME = "log.processing"
ROUTING_KEY = "telemetry.log"


def process_log_event(event_data: dict) -> None:
    """Idempotently store one normalised log record.

    Duplicates are detected by event_id *and* by content hash, so the same
    line re-sent under a new event_id is not stored twice.
    """
    event = TelemetryEventRequest.model_validate(event_data)
    if event.event_type != "log":
        raise ValueError("Expected a log event")

    payload = LogPayload.model_validate(event.payload)
    content_hash = dedup_hash(event.service_name, event.trace_id, payload.span_id,
                              payload.severity, payload.message, event.timestamp)

    def exists(db) -> bool:
        return db.scalar(select(ProcessedLog.id).where(or_(
            ProcessedLog.event_id == event.event_id, ProcessedLog.dedup_hash == content_hash,
        ))) is not None

    with SessionLocal() as db:
        if exists(db):
            logger.info("Duplicate log ignored: event_id=%s", event.event_id)
            return
        db.add(ProcessedLog(
            event_id=event.event_id, trace_id=event.trace_id, span_id=payload.span_id,
            correlation_id=event.correlation_id or payload.correlation_id,
            service_name=event.service_name, severity=payload.severity, message=payload.message,
            timestamp=event.timestamp, message_fingerprint=message_fingerprint(payload.message),
            dedup_hash=content_hash,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if exists(db):
                logger.info("Concurrent duplicate log ignored: event_id=%s", event.event_id)
                return
            raise

    logger.info("Processed log event: event_id=%s severity=%s service=%s",
                event.event_id, payload.severity, event.service_name)


def main() -> None:
    settings.service_name = "log-consumer"
    configure_logging()
    run_consumer(name="log-consumer", queue=QUEUE_NAME, routing_key=ROUTING_KEY,
                 handler=process_log_event)


if __name__ == "__main__":
    main()
