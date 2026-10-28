import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.messaging.consumer_base import run_consumer
from app.models.metric_sample import MetricSample
from app.schemas.metric import MetricPayload
from app.schemas.telemetry import TelemetryEventRequest

logger = logging.getLogger(__name__)

QUEUE_NAME = "metric.processing"
ROUTING_KEY = "telemetry.metric"


def process_metric_event(message: dict) -> None:
    """Idempotently store one raw metric sample (event_id is unique)."""
    event = TelemetryEventRequest.model_validate(message)
    if event.event_type != "metric":
        raise ValueError("Event type must be 'metric'")
    payload = MetricPayload.model_validate(event.payload)

    with SessionLocal() as db:
        if db.scalar(select(MetricSample.id).where(MetricSample.event_id == event.event_id)) is not None:
            logger.info("Metric event already processed: event_id=%s", event.event_id)
            return
        db.add(MetricSample(
            event_id=event.event_id, service_name=event.service_name,
            metric_name=payload.metric_name, metric_value=payload.metric_value,
            trace_id=event.trace_id, recorded_at=event.timestamp,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.scalar(select(MetricSample.id).where(MetricSample.event_id == event.event_id)) is not None:
                logger.info("Concurrent duplicate metric ignored: event_id=%s", event.event_id)
                return
            raise

    logger.info("Processed metric event: event_id=%s metric=%s value=%s service=%s",
                event.event_id, payload.metric_name, payload.metric_value, event.service_name)


def main() -> None:
    settings.service_name = "metric-consumer"
    configure_logging()
    run_consumer(name="metric-consumer", queue=QUEUE_NAME, routing_key=ROUTING_KEY,
                 handler=process_metric_event)


if __name__ == "__main__":
    main()
