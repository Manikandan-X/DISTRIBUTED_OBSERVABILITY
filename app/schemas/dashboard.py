from pydantic import BaseModel, ConfigDict


class DashboardSummaryResponse(BaseModel):
    total_requests: int
    error_rate_percent: float
    average_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None = None
    services_reporting_errors: int
    active_alerts: int
    window_minutes: int | None = None
    partial: bool = False
    warnings: list[str] = []

    model_config = ConfigDict(extra="forbid")
