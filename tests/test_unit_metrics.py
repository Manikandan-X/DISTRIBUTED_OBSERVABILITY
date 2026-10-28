from datetime import timedelta

import pytest

from app.core.stats import error_rate_percent, percentile_nearest_rank, throughput_per_second
from app.db.session import SessionLocal
from app.messaging.metric_consumer import process_metric_event
from app.models.metric_aggregate import MetricAggregate
from app.services import metric_queries
from app.services.metric_aggregation import aggregate_buckets, aggregate_metrics, bucket_floor
from tests.conftest import T0


def metric(event_id, value, name="request_duration_ms", service="svc", at=0, trace=None):
    event = {"event_id": event_id, "event_type": "metric", "service_name": service,
             "timestamp": (T0 + timedelta(seconds=at)).isoformat(),
             "payload": {"metric_name": name, "metric_value": value}}
    if trace:
        event["trace_id"] = trace
    return event


def test_percentile_is_nearest_rank():
    data = [15, 20, 35, 40, 50]
    assert percentile_nearest_rank(data, 30) == 20
    assert percentile_nearest_rank(data, 50) == 35
    assert percentile_nearest_rank(data, 100) == 50
    assert percentile_nearest_rank(data, 0) == 15
    assert percentile_nearest_rank([], 95) is None
    with pytest.raises(ValueError):
        percentile_nearest_rank(data, 101)


def test_p95_returns_an_observed_value():
    values = list(range(1, 101))
    assert percentile_nearest_rank(values, 95) == 95 and percentile_nearest_rank(values, 99) == 99


def test_error_rate_and_throughput():
    assert error_rate_percent(1, 4) == 25.0 and error_rate_percent(0, 0) == 0.0
    assert throughput_per_second(120, 60) == 2.0


def test_aggregation_is_idempotent_and_refreshes_late_samples():
    for i, v in enumerate([10, 20, 30]):
        process_metric_event(metric(f"m{i}", v, at=i))
    with SessionLocal() as db:
        assert aggregate_metrics(db, T0, T0 + timedelta(minutes=1)) == 1
        assert aggregate_metrics(db, T0, T0 + timedelta(minutes=1)) == 1  # re-run: same row
        assert db.query(MetricAggregate).count() == 1
    process_metric_event(metric("late", 100, at=30))  # arrives after the first aggregation
    with SessionLocal() as db:
        aggregate_metrics(db, T0, T0 + timedelta(minutes=1))
        row = db.query(MetricAggregate).one()
        assert row.sample_count == 4 and row.maximum_value == 100
        assert row.percentile_data["p95"] == 100 and row.percentile_data["method"] == "nearest-rank"


def test_same_event_delivered_twice_is_counted_once():
    process_metric_event(metric("dup", 5))
    process_metric_event(metric("dup", 5))
    with SessionLocal() as db:
        aggregate_metrics(db, T0, T0 + timedelta(minutes=1))
        assert db.query(MetricAggregate).one().sample_count == 1


def test_timeseries_reports_missing_intervals_explicitly():
    process_metric_event(metric("a", 10, at=5))
    process_metric_event(metric("b", 30, at=190))  # minute 3; minutes 1-2 have no data
    with SessionLocal() as db:
        aggregate_buckets(db, T0, T0 + timedelta(minutes=4), 60)
        series = metric_queries.timeseries(db, "request_count", "svc", T0, T0 + timedelta(minutes=4), 60)
    values = [(p["value"], p["missing"]) for p in series["points"]]
    assert values == [(1, False), (None, True), (None, True), (1, False)]
    assert series["missing_buckets"] == 2


def test_timeseries_rejects_percentile_without_service_and_bad_range():
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            metric_queries.timeseries(db, "p95_latency", None, T0, T0 + timedelta(minutes=2), 60)
        with pytest.raises(ValueError):
            metric_queries.timeseries(db, "request_count", "s", T0 + timedelta(minutes=2), T0, 60)


def test_bucket_floor_alignment():
    assert bucket_floor(T0 + timedelta(seconds=75), 60) == T0 + timedelta(seconds=60)
