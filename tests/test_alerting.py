
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.alert import Alert
from app.models.metric_sample import MetricSample
from app.services.alerting import evaluate_metric, evaluate_recent_metrics


# Use an isolated in-memory SQLite database for tests.
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
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


def test_creates_alert_when_metric_exceeds_threshold():
    db = TestingSessionLocal()

    try:
        timestamp = datetime(2026, 10, 24, 10, 0, 0)

        alert = evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=150.0,
            threshold_value=100.0,
            evaluated_at=timestamp,
        )

        assert alert is not None
        assert alert.measured_value == 150.0
        assert alert.threshold_value == 100.0
        assert alert.occurrence_count == 1
        assert alert.last_seen_at == timestamp
        assert db.query(Alert).count() == 1
    finally:
        db.close()


def test_does_not_create_alert_when_metric_is_below_threshold():
    db = TestingSessionLocal()

    try:
        alert = evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=80.0,
            threshold_value=100.0,
            evaluated_at=datetime(2026, 10, 24, 10, 0, 0),
        )

        assert alert is None
        assert db.query(Alert).count() == 0
    finally:
        db.close()


def test_repeated_evaluation_does_not_increment_same_timestamp():
    db = TestingSessionLocal()

    try:
        timestamp = datetime(2026, 10, 24, 10, 0, 0)

        evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=150.0,
            threshold_value=100.0,
            evaluated_at=timestamp,
        )

        second_result = evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=150.0,
            threshold_value=100.0,
            evaluated_at=timestamp,
        )

        alert = db.query(Alert).one()

        assert second_result is None
        assert alert.occurrence_count == 1
        assert alert.last_seen_at == timestamp
        assert db.query(Alert).count() == 1
    finally:
        db.close()


def test_newer_sample_updates_existing_alert():
    db = TestingSessionLocal()

    try:
        first_timestamp = datetime(2026, 10, 24, 10, 0, 0)
        second_timestamp = first_timestamp + timedelta(minutes=5)

        evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=125.5,
            threshold_value=100.0,
            evaluated_at=first_timestamp,
        )

        evaluate_metric(
            db=db,
            service_name="payment-service",
            metric_name="request_duration_ms",
            measured_value=150.0,
            threshold_value=100.0,
            evaluated_at=second_timestamp,
        )

        alert = db.query(Alert).one()

        assert alert.measured_value == 150.0
        assert alert.occurrence_count == 2
        assert alert.last_seen_at == second_timestamp
        assert db.query(Alert).count() == 1
    finally:
        db.close()


def test_evaluate_recent_metrics_uses_latest_sample():
    db = TestingSessionLocal()

    try:
        first_timestamp = datetime(2026, 10, 24, 10, 0, 0)
        second_timestamp = first_timestamp + timedelta(minutes=5)

        db.add_all(
            [
                MetricSample(
                    event_id="test-metric-001",
                    service_name="payment-service",
                    metric_name="request_duration_ms",
                    metric_value=125.5,
                    recorded_at=first_timestamp,
                ),
                MetricSample(
                    event_id="test-metric-002",
                    service_name="payment-service",
                    metric_name="request_duration_ms",
                    metric_value=150.0,
                    recorded_at=second_timestamp,
                ),
            ]
        )
        db.commit()

        result = evaluate_recent_metrics(
            db=db,
            thresholds={"request_duration_ms": 100.0},
        )

        alert = db.query(Alert).one()

        assert result == 1
        assert alert.measured_value == 150.0
        assert alert.last_seen_at == second_timestamp
        assert alert.occurrence_count == 1
        assert db.query(Alert).count() == 1
    finally:
        db.close()
