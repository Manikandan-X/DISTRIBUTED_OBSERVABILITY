"""Time-bucketed metric aggregation.

Raw measurements live in ``metric_samples`` (one row per event_id, so an event
can never be counted twice). ``metric_aggregates`` holds per-bucket summaries
(count / avg / min / max / nearest-rank percentiles). Aggregation is a pure
recomputation from raw samples, therefore idempotent: running it again for the
same bucket - or after late samples arrived - overwrites the same row.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.stats import mean, percentile_nearest_rank
from app.core.timeutils import utcnow
from app.models.metric_aggregate import MetricAggregate
from app.models.metric_sample import MetricSample

logger = logging.getLogger(__name__)

METRIC_DURATION = "request_duration_ms"   # one sample per request, value in ms
METRIC_ERROR = "request_error"            # one sample per request: 1 = failed, 0 = ok


def bucket_floor(moment: datetime, bucket_seconds: int) -> datetime:
    """Start of the aligned bucket containing ``moment`` (naive UTC)."""
    seconds = int((moment - datetime(1970, 1, 1)).total_seconds())
    return datetime(1970, 1, 1) + timedelta(seconds=seconds - seconds % bucket_seconds)


def aggregate_metrics(db: Session, interval_start: datetime, interval_end: datetime) -> int:
    """Aggregate every (service, metric) group inside [interval_start, interval_end).

    Returns the number of aggregate rows created or refreshed.
    """
    if interval_end <= interval_start:
        raise ValueError("interval_end must be later than interval_start")

    samples = db.execute(
        select(MetricSample.service_name, MetricSample.metric_name, MetricSample.metric_value)
        .where(MetricSample.recorded_at >= interval_start, MetricSample.recorded_at < interval_end)
    ).all()

    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for service_name, metric_name, value in samples:
        grouped[(service_name, metric_name)].append(float(value))

    processed = 0
    try:
        for (service_name, metric_name), values in grouped.items():
            data = {
                "sample_count": len(values),
                "average_value": mean(values),
                "minimum_value": min(values),
                "maximum_value": max(values),
                "percentile_data": {
                    "method": "nearest-rank",
                    "p50": percentile_nearest_rank(values, 50),
                    "p90": percentile_nearest_rank(values, 90),
                    "p95": percentile_nearest_rank(values, 95),
                    "p99": percentile_nearest_rank(values, 99),
                },
            }
            existing = db.scalar(select(MetricAggregate).where(
                MetricAggregate.service_name == service_name,
                MetricAggregate.metric_name == metric_name,
                MetricAggregate.interval_start == interval_start,
                MetricAggregate.interval_end == interval_end,
            ))
            if existing is None:
                db.add(MetricAggregate(service_name=service_name, metric_name=metric_name,
                                       interval_start=interval_start, interval_end=interval_end, **data))
            else:
                for key, value in data.items():
                    setattr(existing, key, value)
            processed += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Metric aggregation failed")
        raise

    logger.info("Metric aggregation: groups=%s samples=%s interval=%s..%s",
                processed, len(samples), interval_start, interval_end)
    return processed


def aggregate_buckets(db: Session, start: datetime, end: datetime, bucket_seconds: int | None = None) -> int:
    """Aggregate [start, end) as consecutive aligned buckets."""
    bucket_seconds = bucket_seconds or settings.metric_bucket_seconds
    if end <= start:
        raise ValueError("end must be later than start")
    total, cursor = 0, bucket_floor(start, bucket_seconds)
    while cursor < end:
        total += aggregate_metrics(db, cursor, cursor + timedelta(seconds=bucket_seconds))
        cursor += timedelta(seconds=bucket_seconds)
    return total


def aggregate_recent(db: Session, now: datetime | None = None) -> int:
    """Refresh the current bucket and the last N buckets (covers late samples)."""
    now = now or utcnow()
    bucket = settings.metric_bucket_seconds
    start = bucket_floor(now, bucket) - timedelta(seconds=bucket * settings.aggregation_lookback_buckets)
    return aggregate_buckets(db, start, now + timedelta(seconds=1), bucket)
