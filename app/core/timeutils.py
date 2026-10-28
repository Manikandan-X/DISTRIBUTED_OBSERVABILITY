"""Time and identifier normalisation helpers shared by every service."""

import re
from datetime import datetime, timezone

_SERVICE_NAME_RE = re.compile(r"[^a-z0-9._-]+")


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (the storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Normalise any datetime to naive UTC.

    Timezone-aware values are converted to UTC. Naive values are assumed to
    already be UTC.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_service_name(value: str) -> str:
    """Lower-case a service identifier and replace unsafe characters.

    "Payment Service" -> "payment-service". Raises ValueError if nothing
    usable remains.
    """
    cleaned = _SERVICE_NAME_RE.sub("-", value.strip().lower()).strip("-")
    if not cleaned:
        raise ValueError("service_name must contain letters or digits")
    return cleaned[:100]
