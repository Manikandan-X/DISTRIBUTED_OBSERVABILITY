from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.stats import error_rate_percent, mean
from app.models.trace_span import TraceSpan


def build_dependency_graph(
    db: Session,
    trace_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict:
    """Derive the service graph from observed parent/child spans.

    Nothing is hard-coded: an edge A -> B exists only if a span of service B
    was observed as the child of a span of service A.
    """
    filters = []
    if trace_id is not None:
        filters.append(TraceSpan.trace_id == trace_id)
    if start_time is not None:
        filters.append(TraceSpan.start_time >= start_time)
    if end_time is not None:
        filters.append(TraceSpan.start_time <= end_time)

    spans = db.scalars(
        select(TraceSpan).where(*filters).order_by(TraceSpan.start_time.asc(), TraceSpan.id.asc())
    ).all()

    # span ids are only unique within a trace
    span_lookup = {(s.trace_id, s.span_id): s for s in spans}

    nodes: dict[str, dict] = {}
    for span in spans:
        node = nodes.setdefault(span.service_name, {
            "service_name": span.service_name, "span_count": 0, "error_count": 0,
            "traces": set(), "error_traces": set(), "durations": [],
        })
        node["span_count"] += 1
        node["traces"].add(span.trace_id)
        if _is_error(span):
            node["error_count"] += 1
            node["error_traces"].add(span.trace_id)
        if span.duration_ms is not None:
            node["durations"].append(float(span.duration_ms))

    edges: dict[tuple[str, str], dict] = {}
    for child in spans:
        if not child.parent_span_id:
            continue
        parent = span_lookup.get((child.trace_id, child.parent_span_id))
        # No dependency is inferred when the parent was not observed, and
        # same-service parent/child pairs are not service dependencies.
        if parent is None or parent.service_name == child.service_name:
            continue
        edge = edges.setdefault((parent.service_name, child.service_name), {
            "source": parent.service_name, "target": child.service_name,
            "request_count": 0, "error_count": 0, "durations": [], "last_error_at": None,
        })
        edge["request_count"] += 1
        if _is_error(child):
            edge["error_count"] += 1
            if edge["last_error_at"] is None or child.start_time > edge["last_error_at"]:
                edge["last_error_at"] = child.start_time
        if child.duration_ms is not None:
            edge["durations"].append(float(child.duration_ms))

    node_items = []
    for name in sorted(nodes):
        n = nodes[name]
        node_items.append({
            "service_name": name,
            "span_count": n["span_count"],
            "error_count": n["error_count"],
            "request_count": len(n["traces"]),
            "error_rate_percent": error_rate_percent(len(n["error_traces"]), len(n["traces"])),
            "average_duration_ms": mean(n["durations"]),
        })

    edge_items = []
    for key in sorted(edges):
        e = edges[key]
        edge_items.append({
            "source": e["source"], "target": e["target"],
            "request_count": e["request_count"], "error_count": e["error_count"],
            "error_rate_percent": error_rate_percent(e["error_count"], e["request_count"]),
            "average_duration_ms": mean(e["durations"]),
            "observed_failure": e["error_count"] > 0,
            "last_error_at": e["last_error_at"],
        })

    return {
        "trace_id": trace_id, "start_time": start_time, "end_time": end_time,
        "nodes": node_items, "edges": edge_items,
        "failure_relationships": [
            {"source": e["source"], "target": e["target"], "failed_calls": e["error_count"],
             "last_error_at": e["last_error_at"]}
            for e in edge_items if e["observed_failure"]
        ],
    }


def service_dependencies(db: Session, service_name: str, **kwargs) -> dict | None:
    """Incoming/outgoing dependencies for one service (None if unknown)."""
    graph = build_dependency_graph(db, **kwargs)
    node = next((n for n in graph["nodes"] if n["service_name"] == service_name), None)
    if node is None:
        return None
    return {
        "service": node,
        "incoming": [e for e in graph["edges"] if e["target"] == service_name],
        "outgoing": [e for e in graph["edges"] if e["source"] == service_name],
    }


def _is_error(span: TraceSpan) -> bool:
    return span.status.strip().lower() in {"error", "failed", "failure"} or bool(span.error_message)
