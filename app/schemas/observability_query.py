from typing import Any

from pydantic import BaseModel, ConfigDict


class TraceQueryResponse(BaseModel):
    """Composite trace view assembled by the query service.

    ``warnings`` lists anything that could not be retrieved; ``partial`` is
    true when part of the answer is missing because a service failed or the
    caller's role may not see it.
    """

    trace: dict[str, Any]
    spans: list[dict[str, Any]]
    request_path: list[str]
    service_latency: list[dict[str, Any]]
    failed_span_ids: list[str]
    slow_span_ids: list[str]
    missing_parent_span_ids: list[str]
    is_complete: bool
    logs: list[dict[str, Any]]
    diagnostic_reports: list[dict[str, Any]]
    partial: bool
    warnings: list[str]

    model_config = ConfigDict(extra="forbid")
