"""Root-cause analysis orchestration.

The RCA service owns only its report tables. Everything it analyses is
fetched from the owning services over HTTP (traces, logs, metrics, alerts)
with timeouts and bounded retries. If logs/metrics/alerts are unavailable the
report is still produced, with explicit warnings and reduced confidence; if
the trace itself cannot be fetched the analysis fails (503) rather than guess.
"""

import logging

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http_client import DownstreamClient, DownstreamError
from app.models.diagnostic_evidence import DiagnosticEvidence
from app.models.diagnostic_report import DiagnosticReport
from app.services.rca_rules import RULES_VERSION, DiagnosticRules, Evaluation, evaluate
from app.services.trace_analysis import reconstruct_trace

logger = logging.getLogger(__name__)


class TraceNotFoundError(ValueError):
    pass


class TelemetryUnavailableError(RuntimeError):
    pass


def collect_inputs(trace_id: str) -> dict:
    trace_client = DownstreamClient("trace")
    try:
        detail = trace_client.get(f"/api/v1/traces/{trace_id}")
    except DownstreamError as exc:
        if exc.status_code == 404:
            raise TraceNotFoundError(f"Trace not found: {trace_id}") from exc
        raise TelemetryUnavailableError("The trace service is unavailable, so the trace cannot be analysed") from exc

    warnings: list[str] = []
    logs: list[dict] = []
    try:
        logs = DownstreamClient("log").get(f"/api/v1/traces/{trace_id}/logs", {"limit": 500}, role="analyst")["items"]
    except DownstreamError as exc:
        warnings.append(f"Log service unavailable ({exc.kind}); log evidence is missing")

    service_metrics: dict[str, dict] = {}
    try:
        data = DownstreamClient("metrics").get(
            "/api/v1/metrics/services", {"minutes": settings.rca_metric_window_minutes})
        service_metrics = {item["service_name"]: item for item in data["items"]}
    except DownstreamError as exc:
        warnings.append(f"Metrics service unavailable ({exc.kind}); metric evidence is missing")

    alerts: list[dict] = []
    services = {s["service_name"] for s in detail["spans"]}
    try:
        data = DownstreamClient("metrics").get("/api/v1/alerts", {"status": "active", "limit": 200})
        alerts = [a for a in data["items"] if a["service_name"] in services]
    except DownstreamError as exc:
        warnings.append(f"Alert data unavailable ({exc.kind})")

    return {"detail": detail, "logs": logs, "service_metrics": service_metrics, "alerts": alerts, "warnings": warnings}


def build_evidence_items(trace_id: str, ev: Evaluation, spans: dict, logs: list[dict],
                         service_metrics: dict[str, dict], alerts: list[dict]) -> list[dict]:
    items: list[dict] = []
    for sid in dict.fromkeys(ev.origin_span_ids + [f.span_ids[i] for f in ev.findings for i in range(len(f.span_ids))]):
        s = spans.get(sid)
        if s is None:
            continue
        items.append({
            "evidence_type": "trace_span", "reference_id": sid,
            "description": (f"trace={trace_id}; service={s.service_name}; operation={s.operation_name}; "
                            f"status={s.status}; duration_ms={s.duration_ms}; "
                            f"start={s.start_time.isoformat()}; error={s.error_message or 'none'}"),
        })
    for log in logs:
        if str(log.get("severity", "")).upper() in {"ERROR", "CRITICAL"}:
            items.append({
                "evidence_type": "log", "reference_id": log["event_id"],
                "description": (f"service={log['service_name']}; severity={log['severity']}; "
                                f"timestamp={log['timestamp']}; message={log['message'][:300]}"),
            })
    for service in sorted({f.service_name for f in ev.findings}):
        m = service_metrics.get(service)
        if m:
            items.append({
                "evidence_type": "metric", "reference_id": f"{service}:{settings.rca_metric_window_minutes}m",
                "description": (f"service={service}; requests={m.get('request_count')}; "
                                f"error_rate_percent={m.get('error_rate_percent')}; "
                                f"avg_latency_ms={m.get('average_latency_ms')}; p95_latency_ms={m.get('p95_latency_ms')}"),
            })
    for alert in alerts:
        items.append({
            "evidence_type": "alert", "reference_id": str(alert["id"]),
            "description": (f"service={alert['service_name']}; type={alert['alert_type']}; "
                            f"measured={alert['measured_value']}; threshold={alert['threshold_value']}; "
                            f"first_seen={alert['first_seen_at']}"),
        })
    for entry in ev.latency_contribution:
        items.append({
            "evidence_type": "latency", "reference_id": entry["service_name"],
            "description": f"self_time_ms={entry['self_time_ms']}; share={entry['share']:.1%}; spans={entry['span_count']}",
        })
    return items


def analyze_trace(db: Session, trace_id: str, rules: DiagnosticRules | None = None) -> DiagnosticReport:
    rules = rules or DiagnosticRules.from_settings()
    inputs = collect_inputs(trace_id)
    detail = inputs["detail"]
    structure = reconstruct_trace(detail["spans"])

    warnings = list(inputs["warnings"])
    ev = evaluate(structure, inputs["logs"], inputs["service_metrics"], inputs["alerts"], rules,
                  trace_duration_ms=detail["trace"].get("duration_ms"), warnings=warnings)
    items = build_evidence_items(trace_id, ev, structure.spans, inputs["logs"],
                                 inputs["service_metrics"], inputs["alerts"])

    evidence = jsonable_encoder({
        "trace_id": trace_id,
        "root_cause_status": ev.root_cause_status,
        "rules_version": RULES_VERSION,
        "first_failing_span_id": ev.first_failing_span_id,
        "request_path": ev.request_path,
        "failure_timeline": ev.failure_timeline,
        "latency_contribution": ev.latency_contribution,
        "ranked_services": [
            {"service_name": f.service_name, "classification": f.classification,
             "score": round(f.score, 2), "reasons": f.reasons, "span_ids": f.span_ids}
            for f in ev.findings],
        "limitations": ev.limitations,
        "warnings": warnings,
        "span_count": len(structure.spans),
        "failed_span_count": len(ev.origin_span_ids) + sum(1 for f in ev.findings if f.classification == "symptom"),
        "error_log_count": sum(1 for l in inputs["logs"] if str(l.get("severity", "")).upper() in {"ERROR", "CRITICAL"}),
        "related_trace_ids": sorted({t for a in inputs["alerts"] for t in (a.get("trace_ids") or []) if t != trace_id})[:10],
    })

    report = DiagnosticReport(
        trace_id=trace_id, affected_service=ev.affected_service, severity=ev.severity,
        diagnosis=ev.diagnosis, evidence=evidence, confidence_level=ev.confidence,
        root_cause_status=ev.root_cause_status, rules_version=RULES_VERSION,
    )
    try:
        db.add(report)
        db.flush()
        for item in items:
            db.add(DiagnosticEvidence(report_id=report.id, **item))
        db.commit()
        db.refresh(report)
    except Exception:
        db.rollback()
        logger.exception("Failed to store diagnostic report for trace_id=%s", trace_id)
        raise

    logger.info("Root-cause analysis done: trace_id=%s status=%s affected=%s",
                trace_id, ev.root_cause_status, ev.affected_service)
    return report
