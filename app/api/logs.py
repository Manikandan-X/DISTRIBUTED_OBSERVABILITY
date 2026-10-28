"""Log Processing Service - read API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_token, sanitize_filter
from app.db.session import get_db
from app.models.processed_log import ProcessedLog
from app.schemas.log_query import LogPattern, LogPatternResponse, LogQueryItem, LogQueryResponse
from app.services.log_normalization import SEVERITIES, normalize_severity

router = APIRouter(prefix="/api/v1", tags=["Logs"], dependencies=[Depends(require_internal_token)])

TraceId = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _severity(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return normalize_severity(value)
    except ValueError:
        raise HTTPException(422, f"severity must be one of {', '.join(SEVERITIES)}")


def _filters(service_name, severity, trace_id, span_id, correlation_id, start_time, end_time, search):
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise HTTPException(400, "end_time must be later than start_time")
    f = []
    if service_name:
        f.append(ProcessedLog.service_name == service_name)
    if _severity(severity):
        f.append(ProcessedLog.severity == _severity(severity))
    if trace_id:
        f.append(ProcessedLog.trace_id == trace_id)
    if span_id:
        f.append(ProcessedLog.span_id == span_id)
    if correlation_id:
        f.append(ProcessedLog.correlation_id == correlation_id)
    if start_time:
        f.append(ProcessedLog.timestamp >= start_time)
    if end_time:
        f.append(ProcessedLog.timestamp <= end_time)
    if search is not None:
        term = sanitize_filter(search, 500)
        if term:
            # autoescape: user-supplied %, _ are matched literally
            f.append(ProcessedLog.message.contains(term, autoescape=True))
    return f


@router.get("/logs", response_model=LogQueryResponse, summary="Search logs")
def list_logs(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default=None, max_length=20, description="INFO, WARNING, ERROR or CRITICAL"),
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    span_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    correlation_id: str | None = Query(default=None, min_length=1, max_length=100),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=500),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filters = _filters(service_name, severity, trace_id, span_id, correlation_id, start_time, end_time, search)
    total = db.scalar(select(func.count()).select_from(ProcessedLog).where(*filters)) or 0
    items = db.scalars(
        select(ProcessedLog).where(*filters)
        .order_by(ProcessedLog.timestamp.desc(), ProcessedLog.id.desc()).limit(limit).offset(offset)
    ).all()
    return LogQueryResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/logs/patterns", response_model=LogPatternResponse, summary="Repeated log/error patterns")
def log_patterns(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default="ERROR", max_length=20),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    min_count: int = Query(default=2, ge=1, le=100000),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Group messages by fingerprint (ids/numbers masked) and report the
    patterns that repeat at least ``min_count`` times."""
    filters = _filters(service_name, severity, None, None, None, start_time, end_time, None)
    rows = db.execute(
        select(
            ProcessedLog.service_name, ProcessedLog.severity, ProcessedLog.message_fingerprint,
            func.count(ProcessedLog.id), func.min(ProcessedLog.timestamp),
            func.max(ProcessedLog.timestamp), func.min(ProcessedLog.message),
        ).where(*filters)
        .group_by(ProcessedLog.service_name, ProcessedLog.severity, ProcessedLog.message_fingerprint)
        .having(func.count(ProcessedLog.id) >= min_count)
        .order_by(func.count(ProcessedLog.id).desc()).limit(limit)
    ).all()

    items = []
    for service, sev, fingerprint, count, first, last, sample in rows:
        traces = db.scalars(
            select(ProcessedLog.trace_id).where(
                ProcessedLog.service_name == service, ProcessedLog.severity == sev,
                ProcessedLog.message_fingerprint == fingerprint, ProcessedLog.trace_id.isnot(None),
            ).distinct().limit(3)
        ).all()
        items.append(LogPattern(
            service_name=service, severity=sev, fingerprint=fingerprint, sample_message=sample,
            occurrence_count=count, first_seen=first, last_seen=last, example_trace_ids=list(traces),
        ))
    return LogPatternResponse(items=items, total=len(items))


@router.get("/logs/{log_id}", response_model=LogQueryItem, summary="One log record")
def get_log(log_id: int = Path(ge=1), db: Session = Depends(get_db)):
    log = db.get(ProcessedLog, log_id)
    if log is None:
        raise HTTPException(404, "Log not found")
    return log


@router.get("/traces/{trace_id}/logs", response_model=LogQueryResponse, summary="Logs linked to a trace")
def get_trace_logs(
    trace_id: str = TraceId,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filters = [ProcessedLog.trace_id == trace_id]
    total = db.scalar(select(func.count()).select_from(ProcessedLog).where(*filters)) or 0
    items = db.scalars(
        select(ProcessedLog).where(*filters).order_by(ProcessedLog.timestamp.asc(), ProcessedLog.id.asc())
        .limit(limit).offset(offset)
    ).all()
    return LogQueryResponse(items=items, total=total, limit=limit, offset=offset)
