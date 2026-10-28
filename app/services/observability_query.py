"""Query-service composition helpers (no database: everything is fetched from
the owning services over HTTP with timeouts; failures degrade to partial
results with explicit warnings)."""

import logging

from fastapi import HTTPException

from app.core.errors import ApiError
from app.core.http_client import DownstreamClient, DownstreamError
from app.core.security import ROLE_ORDER

logger = logging.getLogger(__name__)

SERVICE_NAMES = {"trace": "trace-service", "log": "log-service", "metrics": "metrics-service",
                 "rca": "rca-service", "ingestion": "ingestion-service"}


def to_api_error(exc: DownstreamError) -> HTTPException:
    """Translate a downstream failure into a client-safe error."""
    name = SERVICE_NAMES.get(exc.service, exc.service)
    if exc.kind == "http_error" and exc.status_code and 400 <= exc.status_code < 500:
        return ApiError(exc.status_code, exc.message, source=name)
    if exc.kind == "timeout":
        return ApiError(504, f"{name} timed out", code="downstream_timeout", source=name)
    if exc.kind == "unavailable":
        return ApiError(503, f"{name} is unavailable", code="downstream_unavailable", source=name)
    return ApiError(502, f"{name} returned an invalid or failing response", code="downstream_error", source=name)


def call(service: str, method: str, path: str, params: dict | None = None, body=None, role: str | None = None):
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        return DownstreamClient(service).request(method, path, params=clean or None, json_body=body, role=role)
    except DownstreamError as exc:
        raise to_api_error(exc) from exc


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER[minimum]


def query_trace(trace_id: str, role: str) -> dict:
    """Trace timeline (required) + logs + diagnostics (best effort)."""
    detail = call("trace", "GET", f"/api/v1/traces/{trace_id}", role=role)  # required: errors propagate
    warnings = list(detail.get("warnings", []))
    partial = False
    logs: list[dict] = []
    reports: list[dict] = []

    if role_at_least(role, "analyst"):
        try:
            logs = DownstreamClient("log").get(f"/api/v1/traces/{trace_id}/logs", {"limit": 500}, role=role)["items"]
        except DownstreamError as exc:
            partial = True
            warnings.append(f"Logs unavailable: {SERVICE_NAMES['log']} {exc.kind}")
        try:
            reports = DownstreamClient("rca").get("/api/v1/diagnostics", {"trace_id": trace_id, "limit": 20},
                                                  role=role)["items"]
        except DownstreamError as exc:
            partial = True
            warnings.append(f"Diagnostic reports unavailable: {SERVICE_NAMES['rca']} {exc.kind}")
    else:
        partial = True
        warnings.append("Logs and diagnostic reports require the 'analyst' role and were omitted")

    return {**detail, "logs": logs, "diagnostic_reports": reports, "partial": partial, "warnings": warnings}
