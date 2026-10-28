"""Pure helpers for normalising log records."""

import hashlib
import re
from datetime import datetime

SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")

_ALIASES = {
    "INFO": "INFO", "INFORMATION": "INFO", "NOTICE": "INFO", "DEBUG": "INFO", "TRACE": "INFO",
    "WARN": "WARNING", "WARNING": "WARNING",
    "ERR": "ERROR", "ERROR": "ERROR", "SEVERE": "ERROR",
    "CRITICAL": "CRITICAL", "FATAL": "CRITICAL", "ALERT": "CRITICAL", "EMERGENCY": "CRITICAL", "EMERG": "CRITICAL",
}

MAX_MESSAGE_LENGTH = 10_000


def normalize_severity(value: str) -> str:
    key = str(value).strip().upper()
    if key not in _ALIASES:
        raise ValueError(f"Unsupported severity '{value}'. Use one of {', '.join(SEVERITIES)}")
    return _ALIASES[key]


def normalize_message(value) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        raise ValueError("message must not be empty")
    return text[:MAX_MESSAGE_LENGTH]


_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{12,}\b")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTED_RE = re.compile(r"(['\"]).*?\1")


def message_fingerprint(message: str) -> str:
    """Stable id for 'the same kind of message'.

    Volatile parts (ids, numbers, quoted values) are masked so repeated error
    patterns group together: "Order 17 failed after 3s" and
    "Order 18 failed after 5s" share one fingerprint.
    """
    masked = _UUID_RE.sub("<uuid>", message)
    masked = _HEX_RE.sub("<hex>", masked)
    masked = _QUOTED_RE.sub("<str>", masked)
    masked = _NUM_RE.sub("<n>", masked)
    masked = re.sub(r"\s+", " ", masked).strip().lower()
    return hashlib.sha1(masked.encode("utf-8")).hexdigest()


def dedup_hash(service_name: str, trace_id: str | None, span_id: str | None,
               severity: str, message: str, timestamp: datetime) -> str:
    """Identity of a log record independent of its event_id.

    The same line delivered under two different event_ids (e.g. a client
    retry that regenerated the id) is stored only once.
    """
    raw = "\x1f".join([service_name, trace_id or "", span_id or "", severity, message, timestamp.isoformat()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
