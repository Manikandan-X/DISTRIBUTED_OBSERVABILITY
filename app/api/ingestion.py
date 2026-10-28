import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_ingestion_key, require_internal_token
from app.db.session import get_db
from app.models.ingestion_event import IngestionEvent
from app.schemas.telemetry import (
    TelemetryBatchRequest,
    TelemetryBatchResponse,
    TelemetryEventRequest,
    TelemetryEventResponse,
)
from app.services.ingestion import ingest_events, ingestion_statistics, relay_failed_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry Ingestion"])

_auth = [Depends(require_ingestion_key)]


def _run(db: Session, request: TelemetryBatchRequest, forced_type: str | None) -> TelemetryBatchResponse:
    if len(request.events) > settings.max_batch_events:
        raise HTTPException(
            413,
            f"A batch may contain at most {settings.max_batch_events} events",
        )
    result = ingest_events(db, request.events, forced_type)
    if result.rejections and not result.accepted and not result.duplicates:
        raise HTTPException(
            422,
            "All events were rejected: " + "; ".join(
                f"[{r['index']}] {', '.join(r['errors'])}" for r in result.rejections[:5]
            ),
        )
    rows = result.accepted + result.duplicates
    return TelemetryBatchResponse(
        received=len(request.events),
        accepted=len(result.accepted),
        duplicates=len(result.duplicates),
        rejected=len(result.rejections),
        queued_for_retry=sum(1 for r in rows if r.processing_status == "publish_failed"),
        event_status=[TelemetryEventResponse.model_validate(r) for r in rows],
        rejections=result.rejections,
    )


@router.post("/logs", response_model=TelemetryBatchResponse, status_code=202, dependencies=_auth,
             summary="Ingest log events")
def ingest_logs(request: TelemetryBatchRequest, db: Session = Depends(get_db)):
    """Accepts ``{"events": [...]}``. Invalid events are rejected individually."""
    return _run(db, request, "log")


@router.post("/traces", response_model=TelemetryBatchResponse, status_code=202, dependencies=_auth,
             summary="Ingest trace/span events")
def ingest_traces(request: TelemetryBatchRequest, db: Session = Depends(get_db)):
    return _run(db, request, "trace")


@router.post("/metrics", response_model=TelemetryBatchResponse, status_code=202, dependencies=_auth,
             summary="Ingest metric events")
def ingest_metrics(request: TelemetryBatchRequest, db: Session = Depends(get_db)):
    return _run(db, request, "metric")


@router.post("/batch", response_model=TelemetryBatchResponse, status_code=202, dependencies=_auth,
             summary="Ingest a mixed batch of logs, traces and metrics")
def ingest_batch(request: TelemetryBatchRequest, db: Session = Depends(get_db)):
    return _run(db, request, None)


@router.post("", response_model=TelemetryEventResponse, status_code=status.HTTP_201_CREATED,
             dependencies=_auth, summary="Ingest one event (legacy single-event endpoint)")
def ingest_telemetry(event: TelemetryEventRequest = Body(...), db: Session = Depends(get_db)):
    existing = db.scalar(select(IngestionEvent).where(IngestionEvent.event_id == event.event_id))
    if existing is not None and existing.processing_status != "publish_failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "An event with this event_id already exists")

    result = ingest_events(db, [event.model_dump(mode="json")])
    row = (result.accepted or result.duplicates)[0]
    if row.processing_status == "publish_failed":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The event is stored but could not be published yet; it will be retried automatically.",
        )
    return row


@router.get("/stats", dependencies=[Depends(require_internal_token)],
            summary="Ingestion success/failure statistics")
def stats(since_minutes: int | None = Query(default=None, ge=1, le=10080), db: Session = Depends(get_db)):
    return ingestion_statistics(db, since_minutes)


@router.post("/retry-failed", dependencies=[Depends(require_internal_token)],
             summary="Administrative: re-publish events that failed to reach the broker")
def retry_failed(db: Session = Depends(get_db)):
    return {"republished": relay_failed_events(db)}
