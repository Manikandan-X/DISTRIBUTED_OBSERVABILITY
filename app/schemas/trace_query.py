from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TraceListItem(BaseModel):
    id: int
    trace_id: str
    root_service: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    status: str
    completed_at: datetime | None
    correlation_id: str | None = None
    span_count: int = 0
    missing_span_count: int = 0
    completion_status: str = "in_progress"

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class TraceListResponse(BaseModel):
    items: list[TraceListItem]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(extra="forbid")


class SpanItem(BaseModel):
    span_id: str
    parent_span_id: str | None
    service_name: str
    operation_name: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    status: str
    error_message: str | None
    correlation_id: str | None = None
    attributes: dict[str, Any] | None = None
    depth: int = 0
    is_failed: bool = False
    is_slow: bool = False
    is_orphan: bool = False          # parent span missing from the trace

    model_config = ConfigDict(extra="forbid")


class TraceDetailResponse(BaseModel):
    trace: TraceListItem
    spans: list[SpanItem]
    request_path: list[str]
    service_latency: list[dict[str, Any]]
    failed_span_ids: list[str]
    slow_span_ids: list[str]
    missing_parent_span_ids: list[str]
    is_complete: bool
    warnings: list[str]

    model_config = ConfigDict(extra="forbid")
