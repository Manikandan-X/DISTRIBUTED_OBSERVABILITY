"""Read-side metric calculations (summary / per-service / latency / time series)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.stats import error_rate_percent, latency_summary, throughput_per_second
from app.core.timeutils import utcnow
from app.models.metric_aggregate import MetricAggregate
from app.models.metric_sample import MetricSample
from app.services.metric_aggregation import METRIC_DURATION, METRIC_ERROR

PERCENTILE_METHOD = "nearest-rank, computed from raw samples inside the window"

SERIES_METRICS = ("request_count", "error_rate", "avg_latency", "p95_latency", "p99_latency", "throughput")


def _raw(db: Session, since: datetime, service_name: str | None = None):
    query = select(MetricSample.service_name, MetricSample.metric_name, MetricSample.metric_value).where(
        MetricSample.recorded_at >= since,
        MetricSample.metric_name.in_([METRIC_DURATION, METRIC_ERROR]),
    )
    if service_name:
        query = query.where(MetricSample.service_name == service_name)
    return db.execute(query).all()


def _stats(durations: list[float], errors: list[float], window_seconds: float) -> dict:
    lat = latency_summary(durations)
    error_count = int(sum(errors))
    return {
        "request_count": len(durations),
        "error_count": error_count,
        "error_rate_percent": error_rate_percent(error_count, len(durations)),
        "average_latency_ms": lat["average"],
        "p50_latency_ms": lat["p50"], "p90_latency_ms": lat["p90"],
        "p95_latency_ms": lat["p95"], "p99_latency_ms": lat["p99"],
        "throughput_per_second": throughput_per_second(len(durations), window_seconds),
    }


def services_metrics(db: Session, minutes: int) -> dict:
    since = utcnow() - timedelta(minutes=minutes)
    per: dict[str, dict[str, list[float]]] = {}
    for service, metric, value in _raw(db, since):
        bucket = per.setdefault(service, {METRIC_DURATION: [], METRIC_ERROR: []})
        bucket[metric].append(float(value))
    items = [{"service_name": name, **_stats(v[METRIC_DURATION], v[METRIC_ERROR], minutes * 60)}
             for name, v in sorted(per.items())]
    return {"window_minutes": minutes, "percentile_method": PERCENTILE_METHOD, "items": items, "total": len(items)}


def summary(db: Session, minutes: int) -> dict:
    since = utcnow() - timedelta(minutes=minutes)
    durations, errors, services = [], [], set()
    for service, metric, value in _raw(db, since):
        services.add(service)
        (durations if metric == METRIC_DURATION else errors).append(float(value))
    return {"window_minutes": minutes, "percentile_method": PERCENTILE_METHOD,
            "services_reporting": len(services), **_stats(durations, errors, minutes * 60)}


def latency(db: Session, minutes: int, service_name: str | None) -> dict:
    since = utcnow() - timedelta(minutes=minutes)
    per: dict[str, list[float]] = {}
    for service, metric, value in _raw(db, since, service_name):
        if metric == METRIC_DURATION:
            per.setdefault(service, []).append(float(value))
    items = [{"service_name": name, **latency_summary(values)} for name, values in sorted(per.items())]
    return {"window_minutes": minutes, "percentile_method": PERCENTILE_METHOD, "items": items}


def timeseries(db: Session, metric: str, service_name: str | None, start: datetime, end: datetime,
               bucket_seconds: int) -> dict:
    """Series from stored aggregates. Intervals without data are returned as
    explicit gaps (``missing: true``, ``value: null``) instead of being skipped."""
    if metric not in SERIES_METRICS:
        raise ValueError(f"metric must be one of {', '.join(SERIES_METRICS)}")
    if bucket_seconds != settings.metric_bucket_seconds:
        raise ValueError(f"Only the configured bucket size is stored: bucket_seconds={settings.metric_bucket_seconds}")
    if end <= start:
        raise ValueError("end_time must be later than start_time")
    if (end - start).total_seconds() / bucket_seconds > 2000:
        raise ValueError("Requested range spans too many buckets (max 2000)")
    if service_name is None and metric in {"p95_latency", "p99_latency"}:
        raise ValueError("Percentile series require service_name (percentiles cannot be merged across services)")

    from app.services.metric_aggregation import bucket_floor

    first = bucket_floor(start, bucket_seconds)
    query = select(MetricAggregate).where(
        MetricAggregate.interval_start >= first, MetricAggregate.interval_start < end,
        MetricAggregate.metric_name.in_([METRIC_DURATION, METRIC_ERROR]),
    )
    if service_name:
        query = query.where(MetricAggregate.service_name == service_name)

    buckets: dict[datetime, dict] = {}
    for row in db.scalars(query).all():
        if (row.interval_end - row.interval_start).total_seconds() != bucket_seconds:
            continue
        b = buckets.setdefault(row.interval_start, {"count": 0, "lat_sum": 0.0, "err_sum": 0.0, "p95": None, "p99": None})
        if row.metric_name == METRIC_DURATION:
            b["count"] += row.sample_count
            b["lat_sum"] += row.average_value * row.sample_count
            pdata = row.percentile_data or {}
            b["p95"], b["p99"] = pdata.get("p95"), pdata.get("p99")
        else:
            b["err_sum"] += row.average_value * row.sample_count

    points, cursor = [], first
    while cursor < end:
        b = buckets.get(cursor)
        value = None
        if b and b["count"]:
            value = {
                "request_count": b["count"],
                "error_rate": round(b["err_sum"] / b["count"] * 100, 4),
                "avg_latency": round(b["lat_sum"] / b["count"], 3),
                "p95_latency": b["p95"], "p99_latency": b["p99"],
                "throughput": round(b["count"] / bucket_seconds, 6),
            }[metric]
        points.append({"bucket_start": cursor, "value": value, "missing": value is None})
        cursor += timedelta(seconds=bucket_seconds)
    return {"metric": metric, "service_name": service_name, "bucket_seconds": bucket_seconds,
            "start_time": first, "end_time": end, "points": points,
            "missing_buckets": sum(1 for p in points if p["missing"])}
