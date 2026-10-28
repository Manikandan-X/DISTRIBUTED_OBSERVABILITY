
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class MetricAggregationRequest(BaseModel):
    interval_start: datetime
    interval_end: datetime

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_interval(self):
        if self.interval_end <= self.interval_start:
            raise ValueError("interval_end must be later than interval_start")
        return self


class MetricAggregationResponse(BaseModel):
    message: str
    aggregates_created: int
