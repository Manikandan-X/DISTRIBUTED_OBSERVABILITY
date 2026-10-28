from datetime import timedelta

from app.services.trace_analysis import (
    detect_slow_spans, failed_span_ids, reconstruct_trace, request_path,
    self_times_ms, service_latency_contribution,
)
from tests.conftest import T0


def sp(i, parent, svc, s, e, status="ok"):
    return dict(span_id=i, parent_span_id=parent, service_name=svc, operation_name=i, status=status,
                start_time=T0 + timedelta(milliseconds=s), end_time=T0 + timedelta(milliseconds=e))


CHAIN = [sp("a", None, "gateway", 0, 100), sp("b", "a", "order", 10, 90), sp("c", "b", "payment", 20, 80)]


def test_parent_child_relationships_and_depth():
    st = reconstruct_trace(CHAIN)
    assert st.roots == ["a"] and st.children["a"] == ["b"] and st.children["b"] == ["c"]
    assert st.depth == {"a": 0, "b": 1, "c": 2}
    assert st.is_complete and st.duration_ms == 100


def test_out_of_order_arrival_gives_same_structure():
    forward = reconstruct_trace(CHAIN)
    shuffled = reconstruct_trace(list(reversed(CHAIN)))
    assert forward.order == shuffled.order == ["a", "b", "c"]
    assert forward.children == shuffled.children


def test_missing_parent_marks_trace_incomplete():
    st = reconstruct_trace([sp("b", "a", "order", 10, 90), sp("c", "b", "payment", 20, 80)])
    assert not st.is_complete
    assert st.missing_parent_ids == ["a"] and st.orphans == ["b"]


def test_duplicate_span_ids_collapse():
    st = reconstruct_trace(CHAIN + [CHAIN[0]])
    assert len(st.spans) == 3


def test_duration_and_self_time_exclude_children():
    st = reconstruct_trace(CHAIN)
    assert self_times_ms(st) == {"a": 20.0, "b": 20.0, "c": 60.0}
    top = service_latency_contribution(st)[0]
    assert top["service_name"] == "payment" and top["share"] == 0.6


def test_parallel_children_are_not_double_subtracted():
    st = reconstruct_trace([sp("a", None, "g", 0, 100), sp("b", "a", "x", 10, 60), sp("c", "a", "y", 20, 70)])
    assert self_times_ms(st)["a"] == 40.0  # children cover 10..70 = 60ms


def test_request_path_and_failures_and_slow():
    spans = CHAIN[:2] + [sp("c", "b", "payment", 20, 80, status="error")]
    st = reconstruct_trace(spans)
    assert request_path(st) == ["gateway", "order", "payment"]
    assert failed_span_ids(st) == ["c"]
    assert detect_slow_spans(st, 70) == {"a", "b", "c"} - {"c"}
