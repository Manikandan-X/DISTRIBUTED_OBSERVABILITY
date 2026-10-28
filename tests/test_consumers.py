import json

import pytest

from app.db.session import SessionLocal
from app.messaging.consumer_base import handle_message
from app.messaging.log_consumer import process_log_event
from app.messaging.trace_consumer import process_trace_event
from app.models.processed_log import ProcessedLog
from app.models.trace import Trace
from app.models.trace_span import TraceSpan
from app.services.trace_completion import finalize_traces
from app.core.timeutils import utcnow
from datetime import timedelta
from tests.conftest import failing_trace, log_event, span_event


def trace_row(trace_id):
    with SessionLocal() as db:
        t = db.query(Trace).filter_by(trace_id=trace_id).one()
        return {c.name: getattr(t, c.name) for c in Trace.__table__.columns}


def test_trace_persistence_and_duration():
    for e in failing_trace():
        process_trace_event(e)
    t = trace_row("t-fail")
    assert t["span_count"] == 3 and t["duration_ms"] == 120 and t["status"] == "error"
    assert t["root_service"] == "api-gateway"


def test_duplicate_delivery_does_not_create_duplicate_spans():
    ev = span_event("t1", "s1", None, "svc", 0, 10)
    for _ in range(3):
        process_trace_event(ev)
    with SessionLocal() as db:
        assert db.query(TraceSpan).count() == 1
    assert trace_row("t1")["span_count"] == 1


def test_out_of_order_events_converge_to_the_same_trace():
    for e in reversed(failing_trace()):       # child spans first, root last
        process_trace_event(e)
    t = trace_row("t-fail")
    assert t["root_service"] == "api-gateway" and t["duration_ms"] == 120 and t["span_count"] == 3
    with SessionLocal() as db:
        finalize_traces(db, wait_seconds=0, now=utcnow() + timedelta(seconds=1))
    assert trace_row("t-fail")["completion_status"] == "complete"


def test_missing_span_marks_trace_incomplete_and_late_span_reopens_it():
    events = failing_trace()
    for e in (events[0], events[2]):          # span b1 (middle) never arrives
        process_trace_event(e)
    with SessionLocal() as db:
        assert finalize_traces(db, wait_seconds=0, now=utcnow() + timedelta(seconds=1)) == 1
    t = trace_row("t-fail")
    assert t["completion_status"] == "incomplete" and t["missing_span_count"] == 1 and t["completed_at"]

    process_trace_event(events[1])            # the late span arrives
    assert trace_row("t-fail")["completion_status"] == "in_progress"
    with SessionLocal() as db:
        finalize_traces(db, wait_seconds=0, now=utcnow() + timedelta(seconds=1))
    assert trace_row("t-fail")["completion_status"] == "complete"


def test_completion_waits_for_the_configured_period():
    process_trace_event(span_event("t2", "s1", None, "svc", 0, 10))
    with SessionLocal() as db:
        assert finalize_traces(db, wait_seconds=3600) == 0
    assert trace_row("t2")["completion_status"] == "in_progress"


def test_original_timestamps_and_relationships_are_preserved():
    process_trace_event(span_event("t3", "s2", "s1", "svc", 5, 9))
    with SessionLocal() as db:
        span = db.query(TraceSpan).one()
        assert span.parent_span_id == "s1" and span.start_time.microsecond == 5000


def test_invalid_trace_event_raises_value_error():
    with pytest.raises(ValueError):
        process_trace_event({"event_type": "log", "service_name": "s", "payload": {"message": "x"}})
    bad = span_event("t4", "s1", None, "svc", 10, 0)  # end before start
    with pytest.raises(ValueError):
        process_trace_event(bad)


def test_log_consumer_dedupes_by_event_id_and_by_content():
    process_log_event(log_event("a", "svc", "ERROR", "boom", trace_id="t1", span_id="s1"))
    process_log_event(log_event("a", "svc", "ERROR", "boom", trace_id="t1", span_id="s1"))      # redelivery
    process_log_event(log_event("b", "svc", "ERROR", "boom", trace_id="t1", span_id="s1"))      # same line, new id
    process_log_event(log_event("c", "svc", "ERROR", "different", trace_id="t1", span_id="s1"))
    with SessionLocal() as db:
        assert db.query(ProcessedLog).count() == 2


def test_log_links_to_trace_and_span():
    process_log_event(log_event("a", "svc", "fatal", "x", trace_id="t9", span_id="s9"))
    with SessionLocal() as db:
        log = db.query(ProcessedLog).one()
        assert (log.trace_id, log.span_id, log.severity) == ("t9", "s9", "CRITICAL")


# ------------------------------------------------------- ack / retry / DLQ
class Method:
    delivery_tag = 1


class Props:
    def __init__(self, headers=None):
        self.headers, self.message_id = headers or {}, "m-1"


class FakeChannel:
    def __init__(self, fail_publish=False):
        self.published, self.acked, self.nacked, self.fail_publish = [], [], [], fail_publish

    def basic_publish(self, **kw):
        if self.fail_publish:
            raise RuntimeError("broker down")
        self.published.append(kw)

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


def deliver(handler, body=b'{"a": 1}', headers=None, channel=None, max_retries=2):
    channel = channel or FakeChannel()
    outcome = handle_message(channel, Method(), Props(headers), body, name="t", handler=handler,
                             queue="q", max_retries=max_retries)
    return outcome, channel


def test_success_is_acked():
    outcome, ch = deliver(lambda m: None)
    assert outcome == "acked" and ch.acked == [1] and not ch.published


def test_invalid_json_and_validation_errors_go_straight_to_dead_letter():
    outcome, ch = deliver(lambda m: None, body=b"{not json")
    assert outcome == "dead_lettered" and ch.published[0]["routing_key"] == "q.dead-letter" and ch.acked == [1]
    assert "dead_letter_reason" in ch.published[0]["properties"].headers

    def bad(m):
        raise ValueError("schema")
    assert deliver(bad)[0] == "dead_lettered"


def test_transient_failure_is_retried_with_counter_then_dead_lettered():
    def broken(m):
        raise RuntimeError("db down")
    outcome, ch = deliver(broken)
    assert outcome == "retry_scheduled" and ch.published[0]["routing_key"] == "q.retry"
    assert ch.published[0]["properties"].headers["x-retry-count"] == 1
    outcome, ch = deliver(broken, headers={"x-retry-count": 2})
    assert outcome == "dead_lettered" and ch.published[0]["routing_key"] == "q.dead-letter"


def test_unable_to_retry_or_dead_letter_requeues_instead_of_losing_the_message():
    def broken(m):
        raise RuntimeError("db down")
    outcome, ch = deliver(broken, channel=FakeChannel(fail_publish=True))
    assert outcome == "requeued" and ch.nacked == [(1, True)] and not ch.acked
