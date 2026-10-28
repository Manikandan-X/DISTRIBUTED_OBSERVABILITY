"""Consistent, safe error responses.

Every error returned by any service has the shape::

    {"error": {"code": "...", "message": "...", "source": "<service>",
               "correlation_id": "...", "details": [...]}}

Stack traces and infrastructure details are logged, never returned.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.context import get_correlation_id

logger = logging.getLogger(__name__)

_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "payload_too_large",
    422: "validation_error", 429: "too_many_requests", 500: "internal_error",
    502: "bad_gateway", 503: "service_unavailable", 504: "gateway_timeout",
}


def error_body(status_code: int, message: str, code: str | None = None,
               details: list | None = None, source: str | None = None) -> dict:
    body = {
        "code": code or _CODES.get(status_code, "error"),
        "message": message,
        "source": source or settings.service_name,
        "correlation_id": get_correlation_id(),
    }
    if details:
        body["details"] = details
    return {"error": body}


def error_response(status_code: int, message: str, code: str | None = None,
                   details: list | None = None, source: str | None = None,
                   headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(status_code, message, code, details, source),
        headers=headers,
    )


class ApiError(HTTPException):
    """HTTPException carrying a machine-readable code and error origin."""

    def __init__(self, status_code: int, message: str, code: str | None = None,
                 source: str | None = None, details: list | None = None, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.error_code = code
        self.error_source = source
        self.error_details = details


def _safe_validation_details(exc: RequestValidationError) -> list[dict]:
    # Drop the echoed "input" so rejected payloads (possibly containing
    # secrets) are never reflected back to the caller.
    return [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "invalid")}
        for err in exc.errors()
    ][:50]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return error_response(
            exc.status_code, message, code=getattr(exc, "error_code", None),
            details=getattr(exc, "error_details", None), source=getattr(exc, "error_source", None),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        return error_response(422, "Request validation failed",
                              details=_safe_validation_details(exc))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "Internal server error")


__all__ = ["ApiError", "HTTPException", "install_error_handlers", "error_response", "error_body"]
