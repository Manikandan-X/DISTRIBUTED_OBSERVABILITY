"""Structured (JSON) application logging with secret redaction."""

import json
import logging
import re
import sys
from datetime import datetime, timezone

from app.core.config import settings
from app.core.context import get_correlation_id

_SECRET_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)([^\s,;'\"]+)"
)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1\2***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.service_name,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "correlation_id": get_correlation_id(),
        }
        if record.exc_info:
            data["exception"] = redact(self.formatException(record.exc_info))
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                data[key] = value if isinstance(value, (int, float, bool, type(None))) else redact(str(value))
        return json.dumps(data, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    for existing in list(root.handlers):
        if getattr(existing, "_obs_json", False):
            root.removeHandler(existing)
    handler._obs_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    for noisy in ("pika", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
