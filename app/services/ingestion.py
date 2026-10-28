"""Telemetry ingestion: validate -> store in outbox -> publish to the broker.

Guarantees
----------
* Malformed events are rejected with per-event error messages and never
  reach the broker.
* Every valid event is persisted (``ingestion_events``) *before* publishing.
  If RabbitMQ is down the event stays ``publish_failed`` and the relay
  re-publishes it later (bounded attempts), so a broker outage does not lose
  data.
* Re-sending an ``event_id`` is idempotent (reported as a duplicate).
* Delivery to consumers is at-least-once, not exactly-once.
"""

import logging
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.timeutils import utcnow
from app.messaging import publisher
from app.messaging.publisher import BrokerUnavailableError
from app.models.ingestion_event import IngestionEvent
from app.schemas.telemetry import TelemetryEventRequest

logger = logging.getLogger(__name__)

MAX_RELAY_ATTEMPTS = 10


@dataclass
class IngestResult:
    accepted: list[IngestionEvent] = field(default_factory=list)
    duplicates: list[IngestionEvent] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)


def _format_errors(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err.get("loc", ()) if p != "__root__")
        message = err.get("msg", "invalid").removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return messages[:10]


def validate_events(raw_events: list, forced_type: str | None = None):
    """Validate each event independently. Returns (valid_events, rejections)."""
    valid: list[tuple[int, TelemetryEventRequest]] = []
    rejections: list[dict] = []
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            rejections.append({"index": index, "event_id": None, "errors": ["event must be a JSON object"]})
            continue
        candidate = dict(raw)
        if forced_type:
            existing = candidate.get("event_type")
            if existing is not None and existing != forced_type:
                rejections.append({"index": index, "event_id": candidate.get("event_id"),
                                   "errors": [f"event_type must be '{forced_type}' for this endpoint"]})
                continue
            candidate["event_type"] = forced_type
        try:
            valid.append((index, TelemetryEventRequest.model_validate(candidate)))
        except ValidationError as exc:
            rejections.append({"index": index, "event_id": candidate.get("event_id")
                               if isinstance(candidate.get("event_id"), str) else None,
                               "errors": _format_errors(exc)})
    return valid, rejections


def ingest_events(db: Session, raw_events: list, forced_type: str | None = None) -> IngestResult:
    result = IngestResult()
    valid, result.rejections = validate_events(raw_events, forced_type)

    to_publish: list[IngestionEvent] = []
    seen_in_batch: set[str] = set()
    for _, event in valid:
        if event.event_id in seen_in_batch:
            existing = db.scalar(select(IngestionEvent).where(IngestionEvent.event_id == event.event_id))
            if existing:
                result.duplicates.append(existing)
            continue
        seen_in_batch.add(event.event_id)

        existing = db.scalar(select(IngestionEvent).where(IngestionEvent.event_id == event.event_id))
        if existing is not None:
            result.duplicates.append(existing)
            if existing.processing_status == "publish_failed":
                to_publish.append(existing)  # client retry re-triggers publishing
            continue

        row = IngestionEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            service_name=event.service_name,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            processing_status="received",
            raw_event=event.model_dump(mode="json"),
            publish_attempts=0,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # concurrent insert of the same event_id
            db.rollback()
            existing = db.scalar(select(IngestionEvent).where(IngestionEvent.event_id == event.event_id))
            if existing:
                result.duplicates.append(existing)
            continue
        db.refresh(row)
        result.accepted.append(row)
        to_publish.append(row)

    _publish_rows(db, to_publish)
    return result


def _publish_rows(db: Session, rows: list[IngestionEvent]) -> None:
    if not rows:
        return
    messages = [row.raw_event for row in rows]
    try:
        publisher.publish_batch(messages)
    except BrokerUnavailableError:
        for row in rows:
            row.processing_status = "publish_failed"
            row.publish_attempts = (row.publish_attempts or 0) + 1
            row.error_message = "Broker unavailable; queued for automatic retry"
        db.commit()
        return
    for row in rows:
        row.processing_status = "published"
        row.publish_attempts = (row.publish_attempts or 0) + 1
        row.error_message = None
    db.commit()


def relay_failed_events(db: Session, batch_size: int = 100) -> int:
    """Re-publish events that could not be sent earlier. Returns how many."""
    rows = db.scalars(
        select(IngestionEvent)
        .where(IngestionEvent.processing_status == "publish_failed",
               IngestionEvent.publish_attempts < MAX_RELAY_ATTEMPTS,
               IngestionEvent.raw_event.isnot(None))
        .order_by(IngestionEvent.id.asc())
        .limit(batch_size)
    ).all()
    if not rows:
        return 0
    _publish_rows(db, list(rows))
    republished = sum(1 for r in rows if r.processing_status == "published")
    if republished:
        logger.info("Outbox relay re-published %s event(s)", republished)
    return republished


def ingestion_statistics(db: Session, since_minutes: int | None = None) -> dict:
    query = select(IngestionEvent.event_type, IngestionEvent.processing_status, func.count())
    if since_minutes:
        from datetime import timedelta

        query = query.where(IngestionEvent.received_at >= utcnow() - timedelta(minutes=since_minutes))
    rows = db.execute(query.group_by(IngestionEvent.event_type, IngestionEvent.processing_status)).all()

    by_type: dict[str, dict[str, int]] = {}
    totals = {"total": 0, "published": 0, "publish_failed": 0, "received": 0}
    for event_type, status, count in rows:
        by_type.setdefault(event_type, {})[status] = count
        totals["total"] += count
        totals[status] = totals.get(status, 0) + count
    success_rate = round(totals["published"] / totals["total"] * 100, 2) if totals["total"] else None
    return {"window_minutes": since_minutes, "totals": totals, "by_type": by_type,
            "publish_success_rate_percent": success_rate}
