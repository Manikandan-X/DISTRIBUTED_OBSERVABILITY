"""Pure trace reconstruction and latency analysis (no I/O).

Used by the trace service (to render timelines / finalise traces) and by the
root-cause service (to apply diagnostic rules to spans fetched over HTTP).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.timeutils import to_naive_utc


def _dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return to_naive_utc(value) if value else None
    return to_naive_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


@dataclass
class SpanNode:
    span_id: str
    parent_span_id: str | None
    service_name: str
    operation_name: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    status: str = "ok"
    error_message: str | None = None
    attributes: dict = field(default_factory=dict)
    correlation_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.status.strip().lower() in {"error", "failed", "failure"} or bool(self.error_message)

    @classmethod
    def from_any(cls, item: Any) -> "SpanNode":
        get = (lambda k: item.get(k)) if isinstance(item, dict) else (lambda k: getattr(item, k, None))
        start, end = _dt(get("start_time")), _dt(get("end_time"))
        duration = get("duration_ms")
        if duration is None and start and end:
            duration = max(0.0, (end - start).total_seconds() * 1000)
        return cls(
            span_id=get("span_id"), parent_span_id=get("parent_span_id") or None,
            service_name=get("service_name"), operation_name=get("operation_name") or "",
            start_time=start, end_time=end, duration_ms=duration,
            status=get("status") or "ok", error_message=get("error_message"),
            attributes=get("attributes") or {},
            correlation_id=get("correlation_id"),
        )


@dataclass
class TraceStructure:
    spans: dict[str, SpanNode]
    children: dict[str, list[str]]
    roots: list[str]
    missing_parent_ids: list[str]      # referenced as parent but never received
    orphans: list[str]                 # spans whose parent is missing
    depth: dict[str, int]
    order: list[str]                   # execution order (start time, then id)

    @property
    def is_complete(self) -> bool:
        return bool(self.roots) and not self.missing_parent_ids

    @property
    def start_time(self) -> datetime | None:
        return min((s.start_time for s in self.spans.values()), default=None)

    @property
    def end_time(self) -> datetime | None:
        ends = [s.end_time for s in self.spans.values() if s.end_time]
        return max(ends, default=None)

    @property
    def duration_ms(self) -> float | None:
        if self.start_time is None or self.end_time is None:
            return None
        return max(0.0, (self.end_time - self.start_time).total_seconds() * 1000)


def reconstruct_trace(raw_spans: list[Any]) -> TraceStructure:
    """Rebuild parent/child relationships regardless of arrival order.

    * duplicate span ids collapse to one span (retried events)
    * a span whose parent is absent is an *orphan* and its parent id is
      reported in ``missing_parent_ids`` (incomplete trace)
    """
    spans: dict[str, SpanNode] = {}
    for item in raw_spans:
        node = item if isinstance(item, SpanNode) else SpanNode.from_any(item)
        spans.setdefault(node.span_id, node)

    children: dict[str, list[str]] = {sid: [] for sid in spans}
    roots, orphans, missing = [], [], set()
    for sid, node in spans.items():
        parent = node.parent_span_id
        if not parent:
            roots.append(sid)
        elif parent in spans:
            children[parent].append(sid)
        else:
            orphans.append(sid)
            missing.add(parent)

    def sort_key(sid: str):
        return (spans[sid].start_time, sid)

    for kids in children.values():
        kids.sort(key=sort_key)
    roots.sort(key=sort_key)
    orphans.sort(key=sort_key)

    depth: dict[str, int] = {}
    stack = [(sid, 0) for sid in reversed(roots + orphans)]
    while stack:
        sid, d = stack.pop()
        if sid in depth:  # guards against malformed cyclic data
            continue
        depth[sid] = d
        stack.extend((kid, d + 1) for kid in reversed(children[sid]))
    for sid in spans:  # cycles / unreachable spans
        depth.setdefault(sid, 0)

    return TraceStructure(
        spans=spans, children=children, roots=roots,
        missing_parent_ids=sorted(missing), orphans=orphans, depth=depth,
        order=sorted(spans, key=sort_key),
    )


def _union_length_ms(intervals: list[tuple[datetime, datetime]]) -> float:
    total, current_start, current_end = 0.0, None, None
    for start, end in sorted(intervals):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += (current_end - current_start).total_seconds() * 1000
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_end is not None:
        total += (current_end - current_start).total_seconds() * 1000
    return total


def self_times_ms(structure: TraceStructure) -> dict[str, float]:
    """Time spent in each span itself, excluding time covered by its children.

    Overlapping (concurrent) children are merged, so parallel calls are not
    double-subtracted.
    """
    result: dict[str, float] = {}
    for sid, node in structure.spans.items():
        duration = node.duration_ms or 0.0
        intervals = []
        for kid_id in structure.children[sid]:
            kid = structure.spans[kid_id]
            if kid.end_time is None or node.end_time is None:
                continue
            start, end = max(kid.start_time, node.start_time), min(kid.end_time, node.end_time)
            if end > start:
                intervals.append((start, end))
        result[sid] = max(0.0, duration - _union_length_ms(intervals))
    return result


def service_latency_contribution(structure: TraceStructure) -> list[dict]:
    """Per-service share of the request's total latency (by self time)."""
    self_times = self_times_ms(structure)
    per_service: dict[str, dict] = {}
    for sid, value in self_times.items():
        name = structure.spans[sid].service_name
        entry = per_service.setdefault(name, {"service_name": name, "self_time_ms": 0.0, "span_count": 0})
        entry["self_time_ms"] += value
        entry["span_count"] += 1
    total = sum(e["self_time_ms"] for e in per_service.values())
    for entry in per_service.values():
        entry["self_time_ms"] = round(entry["self_time_ms"], 3)
        entry["share"] = round(entry["self_time_ms"] / total, 4) if total else 0.0
    return sorted(per_service.values(), key=lambda e: e["self_time_ms"], reverse=True)


def request_path(structure: TraceStructure) -> list[str]:
    """Services in the order the request visited them (depth-first)."""
    path: list[str] = []
    seen: set[str] = set()

    def visit(sid: str):
        if sid in seen:
            return
        seen.add(sid)
        name = structure.spans[sid].service_name
        if not path or path[-1] != name:
            path.append(name)
        for kid in structure.children[sid]:
            visit(kid)

    for sid in structure.roots + structure.orphans:
        visit(sid)
    return path


def detect_slow_spans(structure: TraceStructure, threshold_ms: float) -> set[str]:
    return {sid for sid, s in structure.spans.items() if (s.duration_ms or 0.0) >= threshold_ms}


def failed_span_ids(structure: TraceStructure) -> list[str]:
    return [sid for sid in structure.order if structure.spans[sid].is_error]
