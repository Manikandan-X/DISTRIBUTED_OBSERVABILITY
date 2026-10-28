
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.trace import Trace
from app.models.trace_span import TraceSpan
from app.models.processed_log import ProcessedLog
from app.models.metric_sample import MetricSample
from app.models.diagnostic_report import DiagnosticReport
from app.models.diagnostic_evidence import DiagnosticEvidence
from app.services.root_cause_analysis import analyze_trace


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def setup_function():
    Base.metadata.create_all(bind=engine)


def teardown_function():
    Base.metadata.drop_all(bind=engine)


def add_trace(db, trace_id="trace-test-001"):
    trace = Trace(
        trace_id=trace_id,
        root_service="order-service",
        start_time=datetime(2026, 10, 24, 10, 0, 0),
        end_time=datetime(2026, 10, 24, 10, 0, 2),
        duration_ms=2000.0,
        status="error",
    )
    db.add(trace)
    db.commit()
    return trace


def test_failed_span_produces_high_severity_diagnosis():
    db = TestingSessionLocal()

    try:
        trace_id = "trace-failed-001"
        timestamp = datetime(2026, 10, 24, 10, 0, 0)

        add_trace(db, trace_id)

        db.add(
            TraceSpan(
                trace_id=trace_id,
                span_id="span-failed-001",
                parent_span_id=None,
                service_name="payment-service",
                operation_name="payment.process",
                start_time=timestamp,
                end_time=timestamp + timedelta(milliseconds=50),
                duration_ms=50.0,
                status="error",
                error_message="Payment provider unavailable",
            )
        )
        db.commit()

        report = analyze_trace(db, trace_id)

        assert report.trace_id == trace_id
        assert report.affected_service == "payment-service"
        assert report.severity == "HIGH"
        assert report.confidence_level == 0.9
        assert "Payment provider unavailable" in report.diagnosis
        assert report.evidence["failed_span_count"] == 1

        evidence = (
            db.query(DiagnosticEvidence)
            .filter(DiagnosticEvidence.report_id == report.id)
            .all()
        )
        assert any(item.evidence_type == "trace_span" for item in evidence)

    finally:
        db.close()


def test_error_log_without_failed_span_produces_high_severity():
    db = TestingSessionLocal()

    try:
        trace_id = "trace-log-error-001"
        timestamp = datetime(2026, 10, 24, 10, 0, 0)

        add_trace(db, trace_id)

        db.add(
            ProcessedLog(
                event_id="log-error-001",
                trace_id=trace_id,
                span_id=None,
                service_name="payment-service",
                severity="ERROR",
                message="Payment gateway timeout",
                timestamp=timestamp,
            )
        )
        db.commit()

        report = analyze_trace(db, trace_id)

        assert report.affected_service == "payment-service"
        assert report.severity == "HIGH"
        assert report.confidence_level == 0.8
        assert "Payment gateway timeout" in report.diagnosis
        assert report.evidence["error_log_count"] == 1
        assert report.evidence["failed_span_count"] == 0

        evidence = (
            db.query(DiagnosticEvidence)
            .filter(DiagnosticEvidence.report_id == report.id)
            .all()
        )
        assert any(item.evidence_type == "log" for item in evidence)

    finally:
        db.close()


def test_trace_without_explicit_errors_produces_low_severity():
    db = TestingSessionLocal()

    try:
        trace_id = "trace-healthy-001"
        timestamp = datetime(2026, 10, 24, 10, 0, 0)

        add_trace(db, trace_id)

        db.add(
            TraceSpan(
                trace_id=trace_id,
                span_id="span-healthy-001",
                parent_span_id=None,
                service_name="order-service",
                operation_name="order.create",
                start_time=timestamp,
                end_time=timestamp + timedelta(milliseconds=20),
                duration_ms=20.0,
                status="ok",
                error_message=None,
            )
        )
        db.commit()

        report = analyze_trace(db, trace_id)

        assert report.affected_service == "order-service"
        assert report.severity == "LOW"
        assert report.confidence_level == 0.5
        assert report.evidence["failed_span_count"] == 0
        assert report.evidence["error_log_count"] == 0
        assert "No explicit failed spans" in report.diagnosis

    finally:
        db.close()


def test_missing_trace_raises_value_error():
    db = TestingSessionLocal()

    try:
        try:
            analyze_trace(db, "trace-does-not-exist")
            assert False, "Expected ValueError for missing trace"
        except ValueError as exc:
            assert "Trace not found" in str(exc)

        assert db.query(DiagnosticReport).count() == 0

    finally:
        db.close()
