
from pydantic import BaseModel, ConfigDict


class ServiceHealthItem(BaseModel):
    service_name: str
    request_count: int
    error_count: int
    error_rate_percent: float
    average_latency_ms: float | None
    p95_latency_ms: float | None

    model_config = ConfigDict(extra="forbid")


class ServiceHealthResponse(BaseModel):
    items: list[ServiceHealthItem]
    total: int

    model_config = ConfigDict(extra="forbid")
