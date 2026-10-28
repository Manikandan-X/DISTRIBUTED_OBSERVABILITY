from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_internal_token
from app.core.timeutils import utcnow
from app.db.session import get_db
from app.models.alert import Alert
from app.models.metric_aggregate import MetricAggregate
from app.schemas.metric_query import MetricAggregateQueryResponse
from app.services import metric_queries

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics Query"], dependencies=[Depends(require_internal_token)])


@router.get("/aggregates", response_model=MetricAggregateQueryResponse, summary="Stored time-bucket aggregates")
def get_metric_aggregates(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    metric_name: str | None = Query(default=None, min_length=1, max_length=150),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise HTTPException(400, "end_time must be later than start_time")
    filters = []
    if service_name:
        filters.append(MetricAggregate.service_name == service_name)
    if metric_name:
        filters.append(MetricAggregate.metric_name == metric_name)
    if start_time:
        filters.append(MetricAggregate.interval_start >= start_time)
    if end_time:
        filters.append(MetricAggregate.interval_start <= end_time)
    total = db.scalar(select(func.count()).select_from(MetricAggregate).where(*filters)) or 0
    items = db.scalars(select(MetricAggregate).where(*filters)
                       .order_by(MetricAggregate.interval_start.desc(), MetricAggregate.id.desc())
                       .limit(limit).offset(offset)).all()
    return MetricAggregateQueryResponse(items=items, total=total, limit=limit, offset=offset)


Minutes = Query(default=60, ge=1, le=10080, description="Look-back window in minutes")


@router.get("/services", summary="Per-service requests, error rate, latency percentiles, throughput")
def metrics_services(minutes: int = Minutes, db: Session = Depends(get_db)):
    return metric_queries.services_metrics(db, minutes)


@router.get("/summary", summary="Platform-wide metric summary")
def metrics_summary(minutes: int = Minutes, db: Session = Depends(get_db)):
    data = metric_queries.summary(db, minutes)
    data["active_alerts"] = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "active")) or 0
    return data


@router.get("/latency", summary="Latency distribution (avg/min/max/p50/p90/p95/p99)")
def metrics_latency(minutes: int = Minutes, service_name: str | None = Query(default=None, min_length=1, max_length=100),
                    db: Session = Depends(get_db)):
    return metric_queries.latency(db, minutes, service_name)


@router.get("/timeseries", summary="Time-bucketed series with explicit gaps for missing intervals")
def metrics_timeseries(
    metric: str = Query(default="request_count", description="|".join(metric_queries.SERIES_METRICS)),
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    bucket_seconds: int = Query(default=settings.metric_bucket_seconds, ge=1),
    db: Session = Depends(get_db),
):
    end = end_time or utcnow()
    start = start_time or end - timedelta(minutes=60)
    try:
        return metric_queries.timeseries(db, metric, service_name, start, end, bucket_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
