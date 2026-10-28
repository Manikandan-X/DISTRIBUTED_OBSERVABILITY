from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.trace import sanitize_attributes
from app.services.log_normalization import normalize_message, normalize_severity


class LogPayload(BaseModel):
    """Log payload. Only ``message`` is required; everything else is optional
    so unstructured log lines can be ingested."""

    message: str = Field(max_length=100_000)
    severity: str = Field(default="INFO", max_length=20)
    span_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    correlation_id: str | None = Field(default=None, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str) -> str:
        return normalize_severity(value)

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, value):
        return normalize_message(value)

    @field_validator("span_id")
    @classmethod
    def _empty_span_is_none(cls, value):
        return value or None

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, value: dict) -> dict:
        return sanitize_attributes(value)
