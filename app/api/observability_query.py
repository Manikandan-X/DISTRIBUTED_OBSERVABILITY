"""Observability Query Service: the single read/write API the console uses.

Owns no data. Each endpoint calls the owning service (trace, log, metrics,
rca) over HTTP and either forwards the answer or composes several answers,
degrading to *partial results with explicit warnings* when a non-essential
service is down.
"""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Path, Query

from app.core.errors import ApiError
from app.core.http_client import DownstreamError
from app.core.security import current_role, require_internal_token, require_role
from app.schemas.dashboard import DashboardSummaryResponse
from app.schemas.observability_query import TraceQueryResponse
from app.services import dashboard as dashboard_service
from app.services.observability_query import call, query_trace, to_api_error

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_internal_token)])

TraceId = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
Limit = Query(default=100, ge=1, le=500)
Offset = Query(default=0, ge=0)
Minutes = Query(default=60, ge=1, le=10080)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ------------------------------------------------------------------ traces
@router.get("/traces", tags=["Traces"], summary="Search traces (by trace ID, correlation ID, service, time...)")
def list_traces(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    status: str | None = Query(default=None, min_length=1, max_length=30),
    completion_status: str | None = Query(default=None, pattern="^(in_progress|complete|incomplete)$"),
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    correlation_id: str | None = Query(default=None, min_length=1, max_length=100),
    min_duration_ms: float | None = Query(default=None, ge=0),
    start_time: datetime | None = None, end_time: datetime | None = None,
    limit: int = Limit, offset: int = Offset, role: str = Depends(current_role),
):
    return call("trace", "GET", "/api/v1/traces", {
        "service_name": service_name, "status": status, "completion_status": completion_status,
        "trace_id": trace_id, "correlation_id": correlation_id, "min_duration_ms": min_duration_ms,
        "start_time": _iso(start_time), "end_time": _iso(end_time), "limit": limit, "offset": offset}, role=role)


@router.get("/traces/{trace_id}", tags=["Traces"], response_model=TraceQueryResponse,
            summary="Trace timeline + logs + diagnostics (partial results with warnings)")
def get_trace(trace_id: str = TraceId, role: str = Depends(current_role)):
    return query_trace(trace_id, role)


@router.get("/traces/{trace_id}/spans", tags=["Traces"], summary="Spans of a trace in execution order")
def get_trace_spans(trace_id: str = TraceId, role: str = Depends(current_role)):
    return call("trace", "GET", f"/api/v1/traces/{trace_id}/spans", role=role)


@router.get("/traces/{trace_id}/logs", tags=["Logs"], dependencies=[Depends(require_role("analyst"))],
            summary="Logs linked to a trace")
def get_trace_logs(trace_id: str = TraceId, limit: int = Query(default=200, ge=1, le=500), offset: int = Offset,
                   role: str = Depends(current_role)):
    return call("log", "GET", f"/api/v1/traces/{trace_id}/logs", {"limit": limit, "offset": offset}, role=role)


# -------------------------------------------------------------------- logs
@router.get("/logs", tags=["Logs"], dependencies=[Depends(require_role("analyst"))], summary="Search logs")
def list_logs(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default=None, max_length=20),
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    span_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    correlation_id: str | None = Query(default=None, min_length=1, max_length=100),
    start_time: datetime | None = None, end_time: datetime | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=500),
    limit: int = Limit, offset: int = Offset, role: str = Depends(current_role),
):
    return call("log", "GET", "/api/v1/logs", {
        "service_name": service_name, "severity": severity, "trace_id": trace_id, "span_id": span_id,
        "correlation_id": correlation_id, "start_time": _iso(start_time), "end_time": _iso(end_time),
        "search": search, "limit": limit, "offset": offset}, role=role)


@router.get("/logs/patterns", tags=["Logs"], dependencies=[Depends(require_role("analyst"))],
            summary="Repeated error patterns")
def log_patterns(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default="ERROR", max_length=20),
    start_time: datetime | None = None, end_time: datetime | None = None,
    min_count: int = Query(default=2, ge=1), limit: int = Query(default=50, ge=1, le=200),
    role: str = Depends(current_role),
):
    return call("log", "GET", "/api/v1/logs/patterns", {
        "service_name": service_name, "severity": severity, "start_time": _iso(start_time),
        "end_time": _iso(end_time), "min_count": min_count, "limit": limit}, role=role)


@router.get("/logs/{log_id}", tags=["Logs"], dependencies=[Depends(require_role("analyst"))], summary="One log record")
def get_log(log_id: int = Path(ge=1), role: str = Depends(current_role)):
    return call("log", "GET", f"/api/v1/logs/{log_id}", role=role)


# ----------------------------------------------------------------- metrics
@router.get("/metrics/services", tags=["Metrics"], summary="Per-service metrics")
def metrics_services(minutes: int = Minutes, role: str = Depends(current_role)):
    return call("metrics", "GET", "/api/v1/metrics/services", {"minutes": minutes}, role=role)


@router.get("/metrics/summary", tags=["Metrics"], summary="Platform metric summary")
def metrics_summary(minutes: int = Minutes, role: str = Depends(current_role)):
    return call("metrics", "GET", "/api/v1/metrics/summary", {"minutes": minutes}, role=role)


@router.get("/metrics/latency", tags=["Metrics"], summary="Latency distribution")
def metrics_latency(minutes: int = Minutes, service_name: str | None = Query(default=None, min_length=1, max_length=100),
                    role: str = Depends(current_role)):
    return call("metrics", "GET", "/api/v1/metrics/latency", {"minutes": minutes, "service_name": service_name}, role=role)


@router.get("/metrics/timeseries", tags=["Metrics"], summary="Time-bucketed series")
def metrics_timeseries(
    metric: str = "request_count", service_name: str | None = Query(default=None, min_length=1, max_length=100),
    start_time: datetime | None = None, end_time: datetime | None = None,
    bucket_seconds: int | None = Query(default=None, ge=1), role: str = Depends(current_role),
):
    return call("metrics", "GET", "/api/v1/metrics/timeseries", {
        "metric": metric, "service_name": service_name, "start_time": _iso(start_time),
        "end_time": _iso(end_time), "bucket_seconds": bucket_seconds}, role=role)


@router.get("/metrics/aggregates", tags=["Metrics"], summary="Stored aggregates")
def metrics_aggregates(
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    metric_name: str | None = Query(default=None, min_length=1, max_length=150),
    start_time: datetime | None = None, end_time: datetime | None = None,
    limit: int = Limit, offset: int = Offset, role: str = Depends(current_role),
):
    return call("metrics", "GET", "/api/v1/metrics/aggregates", {
        "service_name": service_name, "metric_name": metric_name, "start_time": _iso(start_time),
        "end_time": _iso(end_time), "limit": limit, "offset": offset}, role=role)


@router.post("/metrics/aggregate", tags=["Metrics"], dependencies=[Depends(require_role("admin"))],
             summary="Administrative: aggregate an explicit interval")
def metrics_aggregate(body: dict = Body(...), role: str = Depends(current_role)):
    return call("metrics", "POST", "/api/v1/metrics/aggregate", body=body, role=role)


# ------------------------------------------------------------ dependencies
@router.get("/dependencies", tags=["Service Dependencies"], summary="Service dependency graph")
def dependencies(
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    start_time: datetime | None = None, end_time: datetime | None = None, role: str = Depends(current_role),
):
    return call("trace", "GET", "/api/v1/dependencies", {
        "trace_id": trace_id, "start_time": _iso(start_time), "end_time": _iso(end_time)}, role=role)


@router.get("/dependencies/{service_name}", tags=["Service Dependencies"], summary="One service's dependencies")
def service_dependencies(service_name: str = Path(min_length=1, max_length=100),
                         start_time: datetime | None = None, end_time: datetime | None = None,
                         role: str = Depends(current_role)):
    return call("trace", "GET", f"/api/v1/dependencies/{service_name}",
                {"start_time": _iso(start_time), "end_time": _iso(end_time)}, role=role)


# ------------------------------------------------------------- diagnostics
_analyst = [Depends(require_role("analyst"))]


@router.get("/diagnostics", tags=["Diagnostics"], dependencies=_analyst, summary="List diagnostic reports")
def list_diagnostics(
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    affected_service: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default=None, pattern="^(LOW|MEDIUM|HIGH)$"),
    root_cause_status: str | None = Query(default=None, pattern="^(confirmed|probable|inconclusive|no_issue_detected)$"),
    limit: int = Limit, offset: int = Offset, role: str = Depends(current_role),
):
    return call("rca", "GET", "/api/v1/diagnostics", {
        "trace_id": trace_id, "affected_service": affected_service, "severity": severity,
        "root_cause_status": root_cause_status, "limit": limit, "offset": offset}, role=role)


@router.get("/diagnostics/{report_id}", tags=["Diagnostics"], dependencies=_analyst, summary="One diagnostic report")
def get_diagnostic(report_id: int = Path(ge=1), role: str = Depends(current_role)):
    return call("rca", "GET", f"/api/v1/diagnostics/{report_id}", role=role)


@router.post("/diagnostics/analyze/{trace_id}", tags=["Diagnostics"], dependencies=_analyst, status_code=201,
             summary="Run root-cause analysis for a trace")
def analyze_trace(trace_id: str = TraceId, role: str = Depends(current_role)):
    return call("rca", "POST", f"/api/v1/diagnostics/analyze/{trace_id}", role=role)


# ------------------------------------------------------------------ alerts
@router.get("/alerts", tags=["Alerts"], summary="List alerts")
def list_alerts(
    status: str | None = Query(default=None, pattern="^(active|acknowledged|resolved)$"),
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    alert_type: str | None = Query(default=None, min_length=1, max_length=50),
    severity: str | None = Query(default=None, pattern="^(warning|critical)$"),
    limit: int = Limit, offset: int = Offset, role: str = Depends(current_role),
):
    return call("metrics", "GET", "/api/v1/alerts", {
        "status": status, "service_name": service_name, "alert_type": alert_type, "severity": severity,
        "limit": limit, "offset": offset}, role=role)


@router.get("/alerts/rules", tags=["Alerts"], summary="Effective alert thresholds")
def alert_rules(role: str = Depends(current_role)):
    return call("metrics", "GET", "/api/v1/alerts/rules", role=role)


@router.put("/alerts/rules", tags=["Alerts"], dependencies=[Depends(require_role("admin"))],
            summary="Create/update a threshold override")
def put_alert_rule(body: dict = Body(...), role: str = Depends(current_role)):
    return call("metrics", "PUT", "/api/v1/alerts/rules", body=body, role=role)


@router.post("/alerts/evaluate", tags=["Alerts"], dependencies=[Depends(require_role("admin"))],
             summary="Administrative: evaluate thresholds now")
def evaluate_alerts(role: str = Depends(current_role)):
    return call("metrics", "POST", "/api/v1/alerts/evaluate", role=role)


@router.get("/alerts/{alert_id}", tags=["Alerts"], summary="One alert with evidence")
def get_alert(alert_id: int = Path(ge=1), role: str = Depends(current_role)):
    return call("metrics", "GET", f"/api/v1/alerts/{alert_id}", role=role)


@router.patch("/alerts/{alert_id}", tags=["Alerts"], dependencies=_analyst, summary="Acknowledge or resolve an alert")
def patch_alert(alert_id: int = Path(ge=1), body: dict = Body(...), role: str = Depends(current_role)):
    return call("metrics", "PATCH", f"/api/v1/alerts/{alert_id}", body=body, role=role)


# ---------------------------------------------------------------- overview
@router.get("/overview", tags=["Overview"], response_model=DashboardSummaryResponse,
            summary="Overview dashboard numbers (partial results with warnings)")
def overview(minutes: int | None = Query(default=None, ge=1, le=10080)):
    try:
        return dashboard_service.get_dashboard_summary(minutes)
    except DownstreamError as exc:
        raise to_api_error(exc) from exc


@router.get("/services/health", tags=["Overview"], summary="Per-service request/error/latency from traces")
def services_health(minutes: int | None = Query(default=None, ge=1, le=10080), role: str = Depends(current_role)):
    return call("trace", "GET", "/api/v1/traces/stats/services", {"since_minutes": minutes}, role=role)


__all__ = ["router", "ApiError"]
