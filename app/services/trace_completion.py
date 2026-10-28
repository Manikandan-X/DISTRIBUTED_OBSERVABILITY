"""Trace completion policy.

A trace is *in progress* while spans keep arriving. Once no span has been
received for ``TRACE_COMPLETION_WAIT_SECONDS`` it is finalised:

* ``complete``   - every span's parent was received and a root span exists
* ``incomplete`` - at least one parent span never arrived (missing span)

A span that arrives after finalisation re-opens the trace (see the trace
consumer) so the policy is re-applied; nothing is lost.
"""

import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutils import utcnow
from app.models.trace import Trace
from app.models.trace_span import TraceSpan
from app.services.trace_analysis import reconstruct_trace

logger = logging.getLogger(__name__)


def finalize_trace(db: Session, trace: Trace, now=None) -> None:
    spans = db.scalars(select(TraceSpan).where(TraceSpan.trace_id == trace.trace_id)).all()
    if not spans:
        return
    structure = reconstruct_trace(list(spans))
    trace.span_count = len(structure.spans)
    trace.missing_span_count = len(structure.missing_parent_ids)
    trace.completion_status = "complete" if structure.is_complete else "incomplete"
    trace.completed_at = now or utcnow()
    trace.start_time = structure.start_time
    trace.end_time = structure.end_time
    trace.duration_ms = structure.duration_ms
    if structure.roots:
        trace.root_service = structure.spans[structure.roots[0]].service_name
    if any(s.is_error for s in structure.spans.values()):
        trace.status = "error"


def finalize_traces(db: Session, wait_seconds: int | None = None, now=None, limit: int = 200) -> int:
    now = now or utcnow()
    cutoff = now - timedelta(seconds=settings.trace_completion_wait_seconds if wait_seconds is None else wait_seconds)
    traces = db.scalars(
        select(Trace)
        .where(Trace.completion_status == "in_progress",
               or_(Trace.last_span_received_at <= cutoff, Trace.last_span_received_at.is_(None)))
        .order_by(Trace.id.asc())
        .limit(limit)
    ).all()
    for trace in traces:
        finalize_trace(db, trace, now)
    if traces:
        db.commit()
        logger.info("Finalised %s trace(s)", len(traces))
    return len(traces)
