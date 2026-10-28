from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AlertResponse(BaseModel):
    id: int
    service_name: str
    alert_type: str
    severity: str = "warning"
    measured_value: float
    threshold_value: float
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    trace_ids: list[str] = Field(default_factory=list)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    limit: int
    offset: int


class AlertUpdateRequest(BaseModel):
    status: Literal["acknowledged", "resolved"]

    model_config = ConfigDict(extra="forbid")


class AlertRuleRequest(BaseModel):
    alert_type: Literal["error_rate_percent", "avg_latency_ms", "p95_latency_ms", "request_volume"]
    service_name: str = Field(default="*", min_length=1, max_length=100)
    threshold_value: float = Field(ge=0)
    enabled: bool = True

    model_config = ConfigDict(extra="forbid")
