import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.timeutils import to_naive_utc

_OK = {"ok", "success", "unset", "succeeded"}
_ERROR = {"error", "failed", "failure", "fail", "fatal", "timeout"}
_SECRET_KEY_RE = re.compile(r"(?i)(password|passwd|secret|token|authorization|api[_-]?key|cookie)")
MAX_ATTRIBUTES = 30


def sanitize_attributes(value: Any) -> dict[str, Any]:
    """Keep a bounded set of scalar attributes, dropping secret-looking keys."""
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if len(clean) >= MAX_ATTRIBUTES:
            break
        key = str(key)[:100]
        if _SECRET_KEY_RE.search(key):
            continue
        if isinstance(item, (bool, int, float)) or item is None:
            clean[key] = item
        elif isinstance(item, str):
            clean[key] = item[:200]
    return clean


class TraceSpanPayload(BaseModel):
    span_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    parent_span_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    operation_name: str = Field(min_length=1, max_length=255)
    start_time: datetime
    end_time: datetime
    status: str = Field(default="ok", max_length=50)
    error_message: str | None = Field(default=None, max_length=5000)
    correlation_id: str | None = Field(default=None, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("start_time", "end_time")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return to_naive_utc(value)

    @field_validator("parent_span_id")
    @classmethod
    def _empty_parent_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        key = value.strip().lower()
        if key in _OK:
            return "ok"
        if key in _ERROR:
            return "error"
        raise ValueError(f"Unsupported span status '{value}'. Use 'ok' or 'error'")

    @field_validator("attributes")
    @classmethod
    def _clean_attributes(cls, value: dict) -> dict:
        return sanitize_attributes(value)

    @model_validator(mode="after")
    def _check_times(self):
        if self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time")
        return self
