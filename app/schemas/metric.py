import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.trace import sanitize_attributes


class MetricPayload(BaseModel):
    metric_name: str = Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:/-]+$")
    metric_value: float
    unit: str | None = Field(default=None, max_length=30)
    labels: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("metric_value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metric_value must be a finite number")
        return value

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: dict) -> dict:
        return sanitize_attributes(value)
