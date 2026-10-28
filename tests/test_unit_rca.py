from datetime import timedelta

from app.services.rca_rules import DiagnosticRules, evaluate, find_origin_failures
from app.services.trace_analysis import reconstruct_trace
from tests.test_unit_trace_analysis import sp

RULES = DiagnosticRules()


def run(spans, logs=(), metrics=None, alerts=(), warnings=()):
    return evaluate(reconstruct_trace(spans), list(logs), metrics or {}, list(alerts), RULES, warnings=list(warnings))


FAILING = [sp("a", None, "gateway", 0, 120, "error"), sp("b", "a", "order", 10, 115, "error"),
           sp("c", "b", "payment", 20, 100, "error")]


def with_msg(spans, sid, msg):
    for s in spans:
        if s["span_id"] == sid:
            s["error_message"] = msg
    return spans


def test_first_failing_span_is_the_origin_not_the_gateway():
    st = reconstruct_trace(FAILING)
    origins, symptoms = find_origin_failures(st)
    assert origins == ["c"] and symptoms == ["a", "b"]


def test_confirmed_failure_names_payment_with_evidence_reasons():
    spans = with_msg([dict(s) for s in FAILING], "c", "Payment provider rejected the transaction")
    ev = run(spans)
    assert ev.root_cause_status == "confirmed" and ev.affected_service == "payment"
    assert ev.first_failing_span_id == "c" and ev.request_path == ["gateway", "order", "payment"]
    top = ev.findings[0]
    assert top.service_name == "payment" and top.classification == "confirmed"
    assert {f.service_name: f.classification for f in ev.findings}["order"] == "symptom"
    assert [t["event"] for t in ev.failure_timeline][0] == "failure origin"


def test_failure_without_error_text_or_logs_is_only_probable():
    ev = run([dict(s) for s in FAILING])
    assert ev.root_cause_status == "probable" and ev.confidence <= 0.6
    assert any("no error message" in l for l in ev.limitations)


def test_error_log_corroboration_upgrades_to_confirmed():
    logs = [{"service_name": "payment", "severity": "ERROR", "message": "declined", "event_id": "e1"}]
    assert run([dict(s) for s in FAILING], logs=logs).root_cause_status == "confirmed"


def test_incomplete_trace_never_claims_confirmed_root_cause():
    spans = with_msg([dict(s) for s in FAILING[1:]], "c", "boom")  # root span missing
    ev = run(spans)
    assert ev.root_cause_status == "probable" and ev.confidence <= 0.6
    assert any("incomplete" in l.lower() for l in ev.limitations)


def test_no_spans_is_inconclusive():
    ev = run([])
    assert ev.root_cause_status == "inconclusive" and ev.confidence == 0.0


def test_latency_bottleneck_without_failures():
    spans = [sp("a", None, "gateway", 0, 3000), sp("b", "a", "order", 50, 2950), sp("c", "b", "payment", 100, 2900)]
    ev = run(spans)
    assert ev.root_cause_status == "confirmed" and ev.affected_service == "payment"
    assert "bottleneck" in ev.diagnosis and ev.severity == "MEDIUM"


def test_healthy_complete_trace_reports_no_issue():
    ev = run([sp("a", None, "gateway", 0, 50), sp("b", "a", "order", 5, 40)])
    assert ev.root_cause_status == "no_issue_detected"


def test_error_logs_alone_do_not_assert_a_root_cause():
    logs = [{"service_name": "order", "severity": "ERROR", "message": "weird", "event_id": "e"}]
    ev = run([sp("a", None, "gateway", 0, 50), sp("b", "a", "order", 5, 40)], logs=logs)
    assert ev.root_cause_status == "inconclusive" and ev.affected_service == "order"


def test_metric_and_alert_signals_rank_potential_causes():
    metrics = {"order": {"error_rate_percent": 40, "request_count": 10, "p95_latency_ms": 2000}}
    alerts = [{"service_name": "order", "alert_type": "error_rate_percent", "severity": "critical"}]
    ev = run([sp("a", None, "gateway", 0, 50), sp("b", "a", "order", 5, 40)], metrics=metrics, alerts=alerts)
    f = next(x for x in ev.findings if x.service_name == "order")
    assert f.classification == "potential" and f.score > 0 and len(f.reasons) == 3


def test_missing_log_service_warning_lowers_confidence():
    spans = with_msg([dict(s) for s in FAILING], "c", "boom")
    clean, degraded = run(spans), run(spans, warnings=["Log service unavailable"])
    assert degraded.confidence < clean.confidence
