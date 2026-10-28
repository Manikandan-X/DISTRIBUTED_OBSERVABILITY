"""Trace Processing Service - read API."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_internal_token
from app.core.stats import error_rate_percent, mean, percentile_nearest_rank
from app.core.timeutils import utcnow
from app.db.session import get_db
from app.models.trace import Trace
from app.models.trace_span import TraceSpan
from app.schemas.service_health import ServiceHealthResponse
from app.schemas.trace_query import SpanItem, TraceDetailResponse, TraceListItem, TraceListResponse
from app.services.service_health import get_service_health
from app.services.trace_analysis import (
    detect_slow_spans,
    failed_span_ids,
    reconstruct_trace,
    request_path,
    service_latency_contribution,
)

router = APIRouter(prefix="/api/v1/traces", tags=["Traces"], dependencies=[Depends(require_internal_token)])

TraceId = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _check_range(start_time: datetime | None, end_time: datetime | None) -> None:
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise HTTPException(400, "end_time must be later than start_time")


def _load_trace(db: Session, trace_id: str) -> Trace:
    trace = db.scalar(select(Trace).where(Trace.trace_id == trace_id))
    if trace is None:
        raise HTTPException(404, f"Trace not found: {trace_id}")
    return trace


@router.get("", response_model=TraceListResponse, summary="Search traces")
def list_traces(
    service_name: str | None = Query(default=None, min_length=1, max_length=100, description="Root service"),
    status: str | None = Query(default=None, min_length=1, max_length=30),
    completion_status: str | None = Query(default=None, pattern="^(in_progress|complete|incomplete)$"),
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    correlation_id: str | None = Query(default=None, min_length=1, max_length=100),
    min_duration_ms: float | None = Query(default=None, ge=0),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _check_range(start_time, end_time)
    filters = []
    if service_name:
        filters.append(Trace.root_service == service_name)
    if status:
        filters.append(Trace.status == status)
    if completion_status:
        filters.append(Trace.completion_status == completion_status)
    if trace_id:
        filters.append(Trace.trace_id == trace_id)
    if correlation_id:
        filters.append(Trace.correlation_id == correlation_id)
    if min_duration_ms is not None:
        filters.append(Trace.duration_ms >= min_duration_ms)
    if start_time:
        filters.append(Trace.start_time >= start_time)
    if end_time:
        filters.append(Trace.start_time <= end_time)

    total = db.scalar(select(func.count()).select_from(Trace).where(*filters)) or 0
    items = db.scalars(
        select(Trace).where(*filters).order_by(Trace.start_time.desc(), Trace.id.desc()).limit(limit).offset(offset)
    ).all()
    return TraceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats/summary", summary="Request totals and latency across traces")
def trace_summary(since_minutes: int | None = Query(default=None, ge=1, le=10080), db: Session = Depends(get_db)):
    """Total requests, error rate, avg and p95/p99 duration (nearest-rank)."""
    filters = []
    if since_minutes:
        filters.append(Trace.start_time >= utcnow() - timedelta(minutes=since_minutes))
    rows = db.execute(select(Trace.status, Trace.duration_ms).where(*filters)).all()
    durations = [float(d) for _, d in rows if d is not None]
    errors = sum(1 for s, _ in rows if (s or "").lower() not in {"ok", "success"})
    services_with_errors = db.scalar(
        select(func.count(func.distinct(TraceSpan.service_name))).where(
            func.lower(TraceSpan.status).notin_({"ok", "success"}),
            *([TraceSpan.start_time >= utcnow() - timedelta(minutes=since_minutes)] if since_minutes else []),
        )
    ) or 0
    return {
        "window_minutes": since_minutes,
        "total_requests": len(rows),
        "failed_requests": errors,
        "error_rate_percent": round(error_rate_percent(errors, len(rows)), 2),
        "average_latency_ms": round(mean(durations), 2) if durations else None,
        "p95_latency_ms": percentile_nearest_rank(durations, 95),
        "p99_latency_ms": percentile_nearest_rank(durations, 99),
        "services_reporting_errors": services_with_errors,
    }


@router.get("/stats/services", response_model=ServiceHealthResponse, summary="Per-service request/error/latency stats")
def services_stats(since_minutes: int | None = Query(default=None, ge=1, le=10080), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(minutes=since_minutes) if since_minutes else None
    return get_service_health(db, since)


@router.get("/{trace_id}", response_model=TraceDetailResponse, summary="Trace with reconstructed timeline")
def get_trace(trace_id: str = TraceId, db: Session = Depends(get_db)):
    trace = _load_trace(db, trace_id)
    spans = db.scalars(select(TraceSpan).where(TraceSpan.trace_id == trace_id)).all()
    structure = reconstruct_trace(list(spans))
    slow = detect_slow_spans(structure, settings.slow_span_threshold_ms)
    failed = failed_span_ids(structure)

    warnings = []
    if structure.missing_parent_ids:
        warnings.append(
            f"Trace is incomplete: {len(structure.missing_parent_ids)} parent span(s) never received "
            f"({', '.join(structure.missing_parent_ids[:5])})"
        )
    if not structure.roots and structure.spans:
        warnings.append("No root span has been received yet")
    if trace.completion_status == "in_progress":
        warnings.append("Trace is still within its completion window; more spans may arrive")

    return TraceDetailResponse(
        trace=TraceListItem.model_validate(trace),
        spans=_span_items(structure, slow),
        request_path=request_path(structure),
        service_latency=service_latency_contribution(structure),
        failed_span_ids=failed,
        slow_span_ids=sorted(slow, key=lambda s: structure.order.index(s)),
        missing_parent_span_ids=structure.missing_parent_ids,
        is_complete=structure.is_complete,
        warnings=warnings,
    )


def _span_items(structure, slow: set[str]) -> list[SpanItem]:
    items = []
    for sid in structure.order:
        s = structure.spans[sid]
        items.append(SpanItem(
            span_id=s.span_id, parent_span_id=s.parent_span_id, service_name=s.service_name,
            operation_name=s.operation_name, start_time=s.start_time, end_time=s.end_time,
            duration_ms=s.duration_ms, status=s.status, error_message=s.error_message,
            correlation_id=s.correlation_id, attributes=s.attributes or None,
            depth=structure.depth.get(sid, 0), is_failed=s.is_error, is_slow=sid in slow,
            is_orphan=sid in structure.orphans,
        ))
    return items


@router.get("/{trace_id}/spans", response_model=list[SpanItem], summary="Spans in execution order")
def get_trace_spans(trace_id: str = TraceId, db: Session = Depends(get_db)):
    _load_trace(db, trace_id)
    rows = db.scalars(select(TraceSpan).where(TraceSpan.trace_id == trace_id)).all()
    structure = reconstruct_trace(list(rows))
    return _span_items(structure, detect_slow_spans(structure, settings.slow_span_threshold_ms))
