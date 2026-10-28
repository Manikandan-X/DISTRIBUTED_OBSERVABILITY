"""Overview dashboard: composed from the trace and metrics services."""

from app.core.http_client import DownstreamClient, DownstreamError

WINDOW_MINUTES = 60


def get_dashboard_summary(minutes: int | None = None) -> dict:
    warnings: list[str] = []
    traces = metrics = None
    try:
        traces = DownstreamClient("trace").get("/api/v1/traces/stats/summary", {"since_minutes": minutes})
    except DownstreamError as exc:
        warnings.append(f"Trace statistics unavailable ({exc.kind}); falling back to metric samples")
    try:
        metrics = DownstreamClient("metrics").get("/api/v1/metrics/summary", {"minutes": minutes or WINDOW_MINUTES})
    except DownstreamError as exc:
        warnings.append(f"Metrics summary unavailable ({exc.kind}); alert count may be missing")

    if traces is None and metrics is None:
        raise DownstreamError("trace", "unavailable", "Neither trace nor metrics statistics could be retrieved")

    if traces is not None:
        data = {
            "total_requests": traces["total_requests"], "error_rate_percent": traces["error_rate_percent"],
            "average_latency_ms": traces["average_latency_ms"], "p95_latency_ms": traces["p95_latency_ms"],
            "p99_latency_ms": traces.get("p99_latency_ms"),
            "services_reporting_errors": traces["services_reporting_errors"],
        }
    else:
        data = {
            "total_requests": metrics["request_count"], "error_rate_percent": round(metrics["error_rate_percent"], 2),
            "average_latency_ms": metrics["average_latency_ms"], "p95_latency_ms": metrics["p95_latency_ms"],
            "p99_latency_ms": metrics["p99_latency_ms"], "services_reporting_errors": 0,
        }
        warnings.append("services_reporting_errors is unavailable without the trace service")
    data["active_alerts"] = metrics["active_alerts"] if metrics is not None else 0
    data["window_minutes"] = minutes
    data["partial"] = bool(warnings)
    data["warnings"] = warnings
    return data
