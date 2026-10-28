"""Threshold alerting with de-duplication.

Evaluated alert types (all configurable via env, overridable per service at
runtime through ``alert_rules``):

* ``error_rate_percent`` - % of failed requests in the latest bucket
* ``avg_latency_ms``     - average request latency in the latest bucket
* ``p95_latency_ms``     - nearest-rank p95 latency in the latest bucket
* ``request_volume``     - requests in the latest bucket (spike detection)

De-duplication / grouping
-------------------------
For one (service, alert_type) there is at most ONE open alert (``active`` or
``acknowledged``). A violation in a *new* evaluation bucket updates that
alert (``last_seen_at``, ``measured_value``, ``occurrence_count``); the same
bucket evaluated twice is ignored. When the metric recovers the alert is
auto-resolved, and a resolved alert cannot re-fire for
``ALERT_COOLDOWN_SECONDS`` (prevents flapping).
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutils import utcnow
from app.models.alert import Alert
from app.models.alert_rule import GLOBAL_SERVICE, AlertRule
from app.models.metric_aggregate import MetricAggregate
from app.models.metric_sample import MetricSample
from app.services.metric_aggregation import METRIC_DURATION, METRIC_ERROR, aggregate_recent, bucket_floor

logger = logging.getLogger(__name__)

ALERT_TYPES = ("error_rate_percent", "avg_latency_ms", "p95_latency_ms", "request_volume")
OPEN_STATUSES = ("active", "acknowledged")
MAX_TRACE_REFS = 10


def default_thresholds() -> dict[str, float]:
    return {
        "error_rate_percent": settings.alert_error_rate_percent,
        "avg_latency_ms": settings.alert_avg_latency_ms,
        "p95_latency_ms": settings.alert_p95_latency_ms,
        "request_volume": settings.alert_request_volume,
    }


def effective_rules(db: Session, service_name: str) -> dict[str, tuple[float, bool]]:
    """threshold + enabled for each alert type (service rule > global rule > env default)."""
    rules = {t: (v, True) for t, v in default_thresholds().items()}
    overrides = db.scalars(select(AlertRule).where(AlertRule.service_name.in_([GLOBAL_SERVICE, service_name]))).all()
    for rule in sorted(overrides, key=lambda r: r.service_name != GLOBAL_SERVICE):  # specific last => wins
        if rule.alert_type in rules:
            rules[rule.alert_type] = (rule.threshold_value, rule.enabled)
    return rules


def _severity(value: float, threshold: float) -> str:
    return "critical" if threshold > 0 and value >= 2 * threshold else "warning"


def evaluate_metric(
    db: Session,
    service_name: str,
    metric_name: str,
    measured_value: float,
    threshold_value: float,
    evaluated_at: datetime | None = None,
    trace_ids: list[str] | None = None,
) -> Alert | None:
    """Create or update an alert when ``measured_value`` exceeds the threshold."""
    if threshold_value < 0:
        raise ValueError("Threshold value cannot be negative.")
    if not service_name.strip():
        raise ValueError("Service name cannot be empty.")
    if not metric_name.strip():
        raise ValueError("Metric name cannot be empty.")

    evaluated_at = evaluated_at or utcnow()
    if measured_value <= threshold_value:
        return None

    try:
        alert = db.scalars(
            select(Alert).where(Alert.service_name == service_name, Alert.alert_type == metric_name,
                                Alert.status.in_(OPEN_STATUSES))
            .order_by(Alert.id.desc())
        ).first()

        if alert is not None:
            if evaluated_at <= alert.last_seen_at:  # same bucket must not be counted twice
                return None
            alert.measured_value = measured_value
            alert.threshold_value = threshold_value
            alert.severity = _severity(measured_value, threshold_value)
            alert.last_seen_at = evaluated_at
            alert.occurrence_count += 1
            alert.trace_ids = _merge_refs(alert.trace_ids, trace_ids)
        else:
            cooldown_start = evaluated_at - timedelta(seconds=settings.alert_cooldown_seconds)
            recently_resolved = db.scalars(
                select(Alert.id).where(Alert.service_name == service_name, Alert.alert_type == metric_name,
                                       Alert.status == "resolved", Alert.resolved_at >= cooldown_start)
            ).first()
            if recently_resolved is not None:
                return None
            alert = Alert(
                service_name=service_name, alert_type=metric_name, measured_value=measured_value,
                threshold_value=threshold_value, status="active", severity=_severity(measured_value, threshold_value),
                first_seen_at=evaluated_at, last_seen_at=evaluated_at, occurrence_count=1,
                trace_ids=_merge_refs(None, trace_ids),
            )
            db.add(alert)

        db.commit()
        db.refresh(alert)
        logger.info("Alert evaluated: service=%s type=%s value=%s threshold=%s",
                    service_name, metric_name, measured_value, threshold_value)
        return alert
    except Exception:
        db.rollback()
        logger.exception("Failed to evaluate alert for service=%s metric=%s", service_name, metric_name)
        raise


def _merge_refs(existing: list | None, new: list[str] | None) -> list[str]:
    merged = list(existing or [])
    for ref in new or []:
        if ref not in merged:
            merged.append(ref)
    return merged[-MAX_TRACE_REFS:]


def resolve_if_recovered(db: Session, service_name: str, alert_type: str, evaluated_at: datetime) -> int:
    alerts = db.scalars(select(Alert).where(
        Alert.service_name == service_name, Alert.alert_type == alert_type,
        Alert.status.in_(OPEN_STATUSES), Alert.last_seen_at < evaluated_at,
    )).all()
    for alert in alerts:
        alert.status, alert.resolved_at = "resolved", evaluated_at
    if alerts:
        db.commit()
        logger.info("Auto-resolved %s alert(s): service=%s type=%s", len(alerts), service_name, alert_type)
    return len(alerts)


def _trace_refs(db: Session, service_name: str, start: datetime, end: datetime, alert_type: str,
                threshold: float) -> list[str]:
    """Concrete traces behind the violation (from samples that carried a trace id)."""
    query = select(MetricSample.trace_id).where(
        MetricSample.service_name == service_name, MetricSample.recorded_at >= start,
        MetricSample.recorded_at < end, MetricSample.trace_id.isnot(None),
    )
    if alert_type == "error_rate_percent":
        query = query.where(MetricSample.metric_name == METRIC_ERROR, MetricSample.metric_value >= 1)
    elif alert_type == "request_volume":
        query = query.where(MetricSample.metric_name == METRIC_DURATION)
    else:
        query = query.where(MetricSample.metric_name == METRIC_DURATION, MetricSample.metric_value > threshold)
        query = query.order_by(MetricSample.metric_value.desc())
    seen: list[str] = []
    for trace_id in db.scalars(query.limit(50)).all():
        if trace_id not in seen:
            seen.append(trace_id)
        if len(seen) >= 5:
            break
    return seen


def evaluate_alerts(db: Session, now: datetime | None = None, refresh_aggregates: bool = True) -> dict:
    """Aggregate recent buckets, then evaluate every service's latest bucket."""
    now = now or utcnow()
    if refresh_aggregates:
        aggregate_recent(db, now)

    bucket = settings.metric_bucket_seconds
    horizon = bucket_floor(now, bucket) - timedelta(seconds=bucket * settings.aggregation_lookback_buckets)
    rows = db.scalars(select(MetricAggregate).where(
        MetricAggregate.interval_start >= horizon,
        MetricAggregate.metric_name.in_([METRIC_DURATION, METRIC_ERROR]),
    ).order_by(MetricAggregate.interval_start.asc())).all()

    latest: dict[str, dict] = {}   # service -> data of its most recent bucket
    for row in rows:
        if (row.interval_end - row.interval_start).total_seconds() != bucket:
            continue
        entry = latest.setdefault(row.service_name, {"start": row.interval_start})
        if row.interval_start > entry["start"]:
            entry.clear(); entry["start"] = row.interval_start
        if row.interval_start == entry["start"]:
            entry[row.metric_name] = row

    created_or_updated = resolved = 0
    for service_name, entry in latest.items():
        duration, errors = entry.get(METRIC_DURATION), entry.get(METRIC_ERROR)
        if duration is None:
            continue
        start, end = entry["start"], entry["start"] + timedelta(seconds=bucket)
        enough = duration.sample_count >= settings.alert_min_samples
        values = {
            "request_volume": float(duration.sample_count),
            # ratios need enough samples: 1 failure out of 1 request is not a trend
            "avg_latency_ms": duration.average_value if enough else None,
            "p95_latency_ms": (duration.percentile_data or {}).get("p95") if enough else None,
            "error_rate_percent": (errors.average_value * 100) if errors is not None and enough else None,
        }
        rules = effective_rules(db, service_name)
        for alert_type, value in values.items():
            threshold, enabled = rules[alert_type]
            if not enabled or value is None:
                continue
            if value > threshold:
                alert = evaluate_metric(db, service_name, alert_type, value, threshold, evaluated_at=end,
                                        trace_ids=_trace_refs(db, service_name, start, end, alert_type, threshold))
                created_or_updated += 1 if alert is not None else 0
            else:
                resolved += resolve_if_recovered(db, service_name, alert_type, end)
    return {"services_evaluated": len(latest), "alerts_created_or_updated": created_or_updated,
            "alerts_resolved": resolved}
