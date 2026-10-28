
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MetricAggregateItem(BaseModel):
    id: int
    service_name: str
    metric_name: str
    interval_start: datetime
    interval_end: datetime
    sample_count: int
    average_value: float
    minimum_value: float
    maximum_value: float
    percentile_data: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MetricAggregateQueryResponse(BaseModel):
    items: list[MetricAggregateItem]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(extra="forbid")
