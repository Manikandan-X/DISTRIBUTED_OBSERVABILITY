from datetime import timedelta

from app.db.session import SessionLocal
from app.messaging.metric_consumer import process_metric_event
from app.models.alert import Alert
from app.models.alert_rule import AlertRule
from app.services.alerting import evaluate_alerts, evaluate_metric
from app.services.metric_aggregation import aggregate_metrics
from tests.conftest import T0
from tests.test_unit_metrics import metric


def test_below_threshold_creates_nothing():
    with SessionLocal() as db:
        assert evaluate_metric(db, "svc", "avg_latency_ms", 100, 500, T0) is None
        assert db.query(Alert).count() == 0


def test_repeated_violations_are_grouped_not_duplicated():
    with SessionLocal() as db:
        first = evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0, trace_ids=["t1"])
        assert first.occurrence_count == 1 and first.status == "active"
        # the same evaluation bucket again must NOT count twice
        assert evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0) is None
        # a later bucket updates the SAME alert
        again = evaluate_metric(db, "svc", "avg_latency_ms", 1200, 500, T0 + timedelta(minutes=1), trace_ids=["t2"])
        assert again.id == first.id and again.occurrence_count == 2 and again.measured_value == 1200
        assert again.trace_ids == ["t1", "t2"]
        assert db.query(Alert).count() == 1


def test_acknowledged_alert_is_not_duplicated_by_new_violation():
    with SessionLocal() as db:
        alert = evaluate_metric(db, "svc", "error_rate_percent", 50, 20, T0)
        alert.status = "acknowledged"
        db.commit()
        evaluate_metric(db, "svc", "error_rate_percent", 60, 20, T0 + timedelta(minutes=1))
        assert db.query(Alert).count() == 1


def test_severity_escalates_at_twice_the_threshold():
    with SessionLocal() as db:
        assert evaluate_metric(db, "a", "avg_latency_ms", 600, 500, T0).severity == "warning"
        assert evaluate_metric(db, "b", "avg_latency_ms", 1000, 500, T0).severity == "critical"


def test_cooldown_blocks_flapping_after_resolution():
    with SessionLocal() as db:
        alert = evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0)
        alert.status, alert.resolved_at = "resolved", T0 + timedelta(seconds=30)
        db.commit()
        assert evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0 + timedelta(seconds=60)) is None
        assert evaluate_metric(db, "svc", "avg_latency_ms", 900, 500, T0 + timedelta(minutes=10)) is not None


def _load(service, durations, errors, at=0):
    for i, (d, e) in enumerate(zip(durations, errors)):
        process_metric_event(metric(f"{service}-d{at}-{i}", d, "request_duration_ms", service, at + i, trace=f"tr-{service}-{i}"))
        process_metric_event(metric(f"{service}-e{at}-{i}", e, "request_error", service, at + i, trace=f"tr-{service}-{i}"))


def test_evaluate_alerts_end_to_end_with_trace_references_and_auto_resolve():
    _load("payment", [100, 100, 3000, 3000], [0, 1, 1, 1])
    now = T0 + timedelta(seconds=50)
    with SessionLocal() as db:
        result = evaluate_alerts(db, now=now)
        types = {a.alert_type for a in db.query(Alert).all()}
        assert {"error_rate_percent", "avg_latency_ms", "p95_latency_ms"} <= types
        err = db.query(Alert).filter(Alert.alert_type == "error_rate_percent").one()
        assert err.measured_value == 75.0 and err.trace_ids  # evidence: failing trace ids
        assert result["alerts_created_or_updated"] >= 3
        assert evaluate_alerts(db, now=now)["alerts_created_or_updated"] == 0   # same bucket: no re-count

    # healthy traffic in the next bucket -> alerts auto-resolve
    _load("payment", [10, 10, 10, 10], [0, 0, 0, 0], at=70)
    with SessionLocal() as db:
        result = evaluate_alerts(db, now=T0 + timedelta(seconds=120))
        assert result["alerts_resolved"] >= 3
        assert db.query(Alert).filter(Alert.status == "active").count() == 0


def test_too_few_samples_do_not_trigger_ratio_alerts():
    _load("tiny", [5000], [1])  # 1 request, 100% errors: not a trend
    with SessionLocal() as db:
        evaluate_alerts(db, now=T0 + timedelta(seconds=50))
        assert db.query(Alert).filter(Alert.alert_type == "error_rate_percent").count() == 0


def test_runtime_rule_override_changes_threshold():
    _load("svc", [100, 100, 100, 100], [0, 0, 0, 0])
    with SessionLocal() as db:
        db.add(AlertRule(alert_type="avg_latency_ms", service_name="svc", threshold_value=50))
        db.commit()
        evaluate_alerts(db, now=T0 + timedelta(seconds=50))
        alert = db.query(Alert).filter(Alert.alert_type == "avg_latency_ms").one()
        assert alert.threshold_value == 50
