from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LogQueryItem(BaseModel):
    id: int
    event_id: str
    trace_id: str | None
    span_id: str | None
    correlation_id: str | None = None
    service_name: str
    severity: str
    message: str
    timestamp: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class LogQueryResponse(BaseModel):
    items: list[LogQueryItem]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(extra="forbid")


class LogPattern(BaseModel):
    service_name: str
    severity: str
    fingerprint: str
    sample_message: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    example_trace_ids: list[str]

    model_config = ConfigDict(extra="forbid")


class LogPatternResponse(BaseModel):
    items: list[LogPattern]
    total: int

    model_config = ConfigDict(extra="forbid")
