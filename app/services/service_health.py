from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.stats import error_rate_percent, mean, percentile_nearest_rank
from app.models.trace_span import TraceSpan
from app.schemas.service_health import ServiceHealthItem, ServiceHealthResponse


def _is_error(span: TraceSpan) -> bool:
    return span.status.strip().lower() in {"error", "failed", "failure"} or bool(span.error_message)


def get_service_health(db: Session, since: datetime | None = None) -> ServiceHealthResponse:
    """Per-service request count (distinct traces), error rate and latency.

    Percentiles use the nearest-rank definition (see app.core.stats).
    """
    query = select(TraceSpan).order_by(TraceSpan.service_name.asc(), TraceSpan.start_time.asc(), TraceSpan.id.asc())
    if since is not None:
        query = query.where(TraceSpan.start_time >= since)

    stats: dict[str, dict] = {}
    for span in db.scalars(query).all():
        s = stats.setdefault(span.service_name, {"traces": set(), "error_traces": set(), "durations": []})
        s["traces"].add(span.trace_id)  # one request can have several spans
        if _is_error(span):
            s["error_traces"].add(span.trace_id)
        if span.duration_ms is not None:
            s["durations"].append(float(span.duration_ms))

    items = []
    for name in sorted(stats):
        s = stats[name]
        avg = mean(s["durations"])
        p95 = percentile_nearest_rank(s["durations"], 95)
        items.append(ServiceHealthItem(
            service_name=name,
            request_count=len(s["traces"]),
            error_count=len(s["error_traces"]),
            error_rate_percent=round(error_rate_percent(len(s["error_traces"]), len(s["traces"])), 2),
            average_latency_ms=round(avg, 2) if avg is not None else None,
            p95_latency_ms=round(p95, 2) if p95 is not None else None,
        ))
    return ServiceHealthResponse(items=items, total=len(items))
