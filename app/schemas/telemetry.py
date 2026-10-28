import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.timeutils import normalize_service_name, to_naive_utc, utcnow
from app.schemas.log import LogPayload
from app.schemas.metric import MetricPayload
from app.schemas.trace import TraceSpanPayload

_PAYLOAD_MODELS = {"trace": TraceSpanPayload, "log": LogPayload, "metric": MetricPayload}


class TelemetryEventRequest(BaseModel):
    """One telemetry event. Validated *before* it can enter the broker."""

    event_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$",
    )
    event_type: Literal["trace", "log", "metric"]
    service_name: str = Field(min_length=1, max_length=100)
    trace_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    correlation_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:-]*$")
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("service_name")
    @classmethod
    def _service(cls, value: str) -> str:
        return normalize_service_name(value)

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return to_naive_utc(value)

    @field_validator("trace_id", "correlation_id")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _validate_payload(self):
        if self.event_type == "trace" and not self.trace_id:
            raise ValueError("trace events must include trace_id")
        model = _PAYLOAD_MODELS[self.event_type].model_validate(self.payload)
        self.payload = model.model_dump(mode="json")
        # Preserve the correlation ID wherever the client supplied it.
        if not self.correlation_id:
            self.correlation_id = self.payload.get("correlation_id")
        return self


class TelemetryEventResponse(BaseModel):
    event_id: str
    event_type: str
    service_name: str
    trace_id: str | None
    processing_status: str

    model_config = ConfigDict(from_attributes=True)


class TelemetryBatchRequest(BaseModel):
    events: list[Any] = Field(min_length=1)  # validated one by one so a single bad event cannot reject the batch

    model_config = ConfigDict(extra="forbid")


class TelemetryRejection(BaseModel):
    index: int
    event_id: str | None = None
    errors: list[str]


class TelemetryBatchResponse(BaseModel):
    received: int
    accepted: int
    duplicates: int
    rejected: int
    queued_for_retry: int
    event_status: list[TelemetryEventResponse]
    rejections: list[TelemetryRejection]
