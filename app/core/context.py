"""Request-scoped context (correlation ID, caller identity)."""

import re
import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Correlation-ID"
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def sanitize_correlation_id(value: str | None) -> str | None:
    """Accept only a safe, bounded correlation ID from untrusted input."""
    if value and _CORRELATION_RE.match(value):
        return value
    return None


def set_correlation_id(value: str | None):
    return _correlation_id.set(value)


def reset_correlation_id(token) -> None:
    _correlation_id.reset(token)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def outbound_headers() -> dict[str, str]:
    """Headers that propagate the current correlation ID downstream."""
    cid = get_correlation_id()
    return {CORRELATION_HEADER: cid} if cid else {}
