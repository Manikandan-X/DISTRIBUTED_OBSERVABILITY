"""Deterministic root-cause rules (pure functions, no I/O, no paid AI).

Vocabulary
----------
* ``classification``
    - ``confirmed``  : directly observed in the trace (a failed span, or a
                       measured latency bottleneck)
    - ``potential``  : only corroborating signals (error logs, elevated
                       service error rate / latency, active alerts)
    - ``symptom``    : a failure that is explained by a failing downstream span
* ``root_cause_status`` of a report
    - ``confirmed``         origin failing span observed in a COMPLETE trace
    - ``probable``          failure/bottleneck observed but evidence is partial
                            (incomplete trace, missing logs/metrics, no error text)
    - ``inconclusive``      signals exist but cannot name a cause
    - ``no_issue_detected`` complete trace, no failure, no bottleneck

A root cause is never claimed when telemetry is insufficient.
"""

from dataclasses import dataclass, field

from app.core.config import settings
from app.services.trace_analysis import (
    TraceStructure,
    failed_span_ids,
    request_path,
    self_times_ms,
    service_latency_contribution,
)

RULES_VERSION = "1.0"
ERROR_SEVERITIES = {"ERROR", "CRITICAL"}


@dataclass
class DiagnosticRules:
    failed_origin_weight: float = 50.0
    failed_symptom_weight: float = 15.0
    error_log_weight: float = 3.0
    error_log_cap: float = 15.0
    latency_share_weight: float = 30.0
    elevated_error_rate_weight: float = 15.0
    elevated_latency_weight: float = 10.0
    active_alert_weight: float = 10.0
    bottleneck_min_share: float = 0.5
    slow_span_threshold_ms: float = 500.0
    slow_trace_threshold_ms: float = 1000.0
    elevated_error_rate_percent: float = 20.0
    elevated_p95_ms: float = 1000.0

    @classmethod
    def from_settings(cls) -> "DiagnosticRules":
        return cls(
            failed_origin_weight=settings.rca_failed_origin_weight,
            failed_symptom_weight=settings.rca_failed_symptom_weight,
            error_log_weight=settings.rca_error_log_weight,
            latency_share_weight=settings.rca_latency_share_weight,
            elevated_error_rate_weight=settings.rca_elevated_error_rate_weight,
            elevated_latency_weight=settings.rca_elevated_latency_weight,
            active_alert_weight=settings.rca_active_alert_weight,
            bottleneck_min_share=settings.rca_bottleneck_min_share,
            slow_span_threshold_ms=settings.slow_span_threshold_ms,
            slow_trace_threshold_ms=settings.slow_trace_threshold_ms,
            elevated_error_rate_percent=settings.alert_error_rate_percent,
            elevated_p95_ms=settings.alert_p95_latency_ms,
        )


@dataclass
class Finding:
    service_name: str
    classification: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    span_ids: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    root_cause_status: str
    severity: str
    confidence: float
    affected_service: str
    diagnosis: str
    findings: list[Finding]
    first_failing_span_id: str | None
    origin_span_ids: list[str]
    latency_contribution: list[dict]
    request_path: list[str]
    failure_timeline: list[dict]
    limitations: list[str]


def find_origin_failures(structure: TraceStructure) -> tuple[list[str], list[str]]:
    """Split failed spans into (origins, symptoms).

    An *origin* is a failed span with no failed descendant: it is where the
    failure started. Failed ancestors merely propagate it (symptoms).
    """
    failed = set(failed_span_ids(structure))
    has_failed_descendant: set[str] = set()

    def mark(sid: str) -> bool:
        found = False
        for kid in structure.children.get(sid, []):
            kid_has_failure = mark(kid)  # always recurse: a failed child may itself have failed children
            if kid in failed or kid_has_failure:
                found = True
        if found:
            has_failed_descendant.add(sid)
        return found

    for sid in structure.roots + structure.orphans:
        mark(sid)
    ordered = failed_span_ids(structure)
    origins = [s for s in ordered if s not in has_failed_descendant]
    symptoms = [s for s in ordered if s in has_failed_descendant]
    # first observed failure = earliest END time (errors surface bottom-up)
    origins.sort(key=lambda s: (structure.spans[s].end_time or structure.spans[s].start_time, s))
    return origins, symptoms


def evaluate(structure: TraceStructure, logs: list[dict], service_metrics: dict[str, dict],
             alerts: list[dict], rules: DiagnosticRules, trace_duration_ms: float | None = None,
             warnings: list[str] | None = None) -> Evaluation:
    warnings = list(warnings or [])
    limitations = list(warnings)
    spans = structure.spans
    latency = service_latency_contribution(structure)
    path = request_path(structure) if spans else []
    duration = trace_duration_ms if trace_duration_ms is not None else structure.duration_ms

    findings: dict[str, Finding] = {}

    def finding(service: str, classification: str) -> Finding:
        f = findings.get(service)
        if f is None:
            f = findings[service] = Finding(service, classification)
        elif classification == "confirmed" and f.classification != "confirmed":
            f.classification = "confirmed"
        return f

    if not spans:
        return Evaluation("inconclusive", "LOW", 0.0, "unknown",
                          "No spans are available for this trace, so no diagnosis can be made.",
                          [], None, [], [], [], [], ["No spans received for the trace"] + limitations)

    incomplete = not structure.is_complete
    if incomplete:
        limitations.append(
            f"Trace is incomplete: {len(structure.missing_parent_ids)} parent span(s) never received"
            if structure.missing_parent_ids else "No root span has been received")

    origins, symptoms = find_origin_failures(structure)
    error_logs = [l for l in logs if str(l.get("severity", "")).upper() in ERROR_SEVERITIES]

    # ---- rule 1: failed spans ------------------------------------------------
    for sid in origins:
        s = spans[sid]
        f = finding(s.service_name, "confirmed")
        f.score += rules.failed_origin_weight
        f.span_ids.append(sid)
        f.reasons.append(f"Origin of failure: span '{s.operation_name}' failed"
                         + (f" ({s.error_message})" if s.error_message else ""))
    for sid in symptoms:
        s = spans[sid]
        f = finding(s.service_name, "symptom")
        f.score += rules.failed_symptom_weight
        f.span_ids.append(sid)
        f.reasons.append(f"Failure propagated through span '{s.operation_name}'")

    # ---- rule 2: latency bottleneck -------------------------------------------
    self_times = self_times_ms(structure)
    bottleneck_sid = None
    if self_times:
        top_sid = max(self_times, key=self_times.get)
        top = spans[top_sid]
        total_self = sum(self_times.values()) or 1.0
        share = self_times[top_sid] / total_self
        slow = self_times[top_sid] >= rules.slow_span_threshold_ms or (
            duration is not None and duration >= rules.slow_trace_threshold_ms
            and share >= rules.bottleneck_min_share)
        if slow and share >= rules.bottleneck_min_share:
            bottleneck_sid = top_sid
            f = finding(top.service_name, "confirmed")
            f.score += rules.latency_share_weight * share
            f.span_ids.append(top_sid)
            f.reasons.append(f"Latency bottleneck: span '{top.operation_name}' spent "
                             f"{self_times[top_sid]:.0f} ms ({share:.0%} of the request) in itself")
    # ---- rule 3: corroborating signals ---------------------------------------
    logs_by_service: dict[str, int] = {}
    for l in error_logs:
        logs_by_service[l["service_name"]] = logs_by_service.get(l["service_name"], 0) + 1
    for service, count in logs_by_service.items():
        f = finding(service, "potential")
        f.score += min(rules.error_log_cap, rules.error_log_weight * count)
        f.reasons.append(f"{count} error-level log record(s) linked to this trace")

    for service in {s.service_name for s in spans.values()}:
        m = service_metrics.get(service)
        if not m:
            continue
        if (m.get("error_rate_percent") or 0) >= rules.elevated_error_rate_percent and m.get("request_count", 0) > 0:
            f = finding(service, "potential")
            f.score += rules.elevated_error_rate_weight
            f.reasons.append(f"Service error rate is elevated ({m['error_rate_percent']:.1f}% over the recent window)")
        if (m.get("p95_latency_ms") or 0) >= rules.elevated_p95_ms:
            f = finding(service, "potential")
            f.score += rules.elevated_latency_weight
            f.reasons.append(f"Service p95 latency is elevated ({m['p95_latency_ms']:.0f} ms)")
    for alert in alerts:
        f = finding(alert["service_name"], "potential")
        f.score += rules.active_alert_weight
        f.reasons.append(f"Active {alert.get('severity', 'warning')} alert: {alert['alert_type']}")

    ranked = sorted(findings.values(), key=lambda f: (-f.score, f.service_name))

    # ---- verdict ------------------------------------------------------------
    first_failing = origins[0] if origins else None
    timeline = [
        {"timestamp": spans[sid].end_time or spans[sid].start_time, "service_name": spans[sid].service_name,
         "span_id": sid, "event": ("failure origin" if sid in origins else "failure propagated")}
        for sid in sorted(origins + symptoms, key=lambda s: (spans[s].end_time or spans[s].start_time, s))
    ]

    if origins:
        origin = spans[first_failing]
        affected = origin.service_name
        has_detail = bool(origin.error_message)
        corroborated = bool(logs_by_service.get(affected)) or any(
            a["service_name"] == affected for a in alerts)
        if not incomplete and (has_detail or corroborated):
            status, confidence = "confirmed", 0.9 if (has_detail and corroborated) else 0.8
        else:
            status, confidence = "probable", 0.6
            if not has_detail and not corroborated:
                limitations.append("The failing span carries no error message and no corroborating logs were found")
        if incomplete:
            confidence = min(confidence, 0.6)
            limitations.append("Spans of the trace are missing, so a failure further downstream cannot be ruled out")
        if warnings:
            confidence = max(0.3, confidence - 0.1)
        severity = "HIGH" if not incomplete else "MEDIUM"
        diagnosis = (f"The first observed failure is in {affected} (operation '{origin.operation_name}'"
                     + (f": {origin.error_message}" if origin.error_message else "") + "). "
                     f"{len(symptoms)} upstream span(s) failed as a consequence. "
                     f"Root cause is {status}.")
    elif bottleneck_sid:
        b = spans[bottleneck_sid]
        affected = b.service_name
        status = "confirmed" if not incomplete else "probable"
        confidence = 0.8 if not incomplete else 0.55
        severity = "MEDIUM"
        diagnosis = (f"No failed spans. The latency bottleneck is {affected} (operation '{b.operation_name}'), "
                     f"which accounts for {self_times[bottleneck_sid]:.0f} ms of the request. "
                     "This identifies where time was spent, not why the service was slow.")
    elif error_logs:
        affected = error_logs[0]["service_name"]
        status, confidence, severity = "inconclusive", 0.4, "MEDIUM"
        diagnosis = (f"No failed span was recorded, but {len(error_logs)} error-level log(s) exist, first from "
                     f"{affected}: {error_logs[0]['message'][:200]}. The cause cannot be confirmed from the trace alone.")
        limitations.append("Error logs exist without a failed span; root cause not asserted")
    elif incomplete:
        affected = spans[structure.order[0]].service_name
        status, confidence, severity = "inconclusive", 0.3, "LOW"
        diagnosis = "No failure or bottleneck is visible, but the trace is incomplete so problems cannot be ruled out."
    else:
        affected = spans[structure.roots[0]].service_name if structure.roots else spans[structure.order[0]].service_name
        status, confidence, severity = "no_issue_detected", 0.7, "LOW"
        diagnosis = "No failed spans, error logs or latency bottlenecks were found in this complete trace."

    return Evaluation(
        root_cause_status=status, severity=severity, confidence=round(confidence, 2),
        affected_service=affected, diagnosis=diagnosis, findings=ranked,
        first_failing_span_id=first_failing, origin_span_ids=origins,
        latency_contribution=latency, request_path=path, failure_timeline=timeline,
        limitations=limitations,
    )
