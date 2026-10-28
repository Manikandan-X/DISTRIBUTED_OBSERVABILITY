"""Pure-ASGI middleware: correlation IDs and request-size limiting."""

import json

from app.core.config import settings
from app.core.context import (
    CORRELATION_HEADER,
    new_correlation_id,
    reset_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)


class CorrelationIdMiddleware:
    """Read (or create) X-Correlation-ID, expose it via contextvar + response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-correlation-id":
                incoming = value.decode("latin-1")
                break
        cid = sanitize_correlation_id(incoming) or new_correlation_id()
        token = set_correlation_id(cid)
        scope.setdefault("state", {})["correlation_id"] = cid

        try:
            from opentelemetry import trace as otel_trace

            span = otel_trace.get_current_span()
            if span.get_span_context().is_valid:
                span.set_attribute("correlation.id", cid)
        except Exception:  # tracing must never break a request
            pass

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-correlation-id"]
                headers.append((CORRELATION_HEADER.lower().encode(), cid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            reset_correlation_id(token)


class MaxBodySizeMiddleware:
    """Reject request bodies larger than ``max_bytes`` with HTTP 413.

    Checks Content-Length up-front and also counts streamed bytes, so
    chunked uploads cannot bypass the limit.
    """

    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        limit = self.max_bytes or settings.max_request_bytes
        declared = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break

        if declared is not None and declared > limit:
            return await self._reject(send, limit)

        received = 0
        too_large = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        responded = False

        async def guarded_send(message):
            nonlocal responded
            if too_large and not responded:
                responded = True
                await self._reject(send, limit)
                return
            if not responded:
                await send(message)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send, limit: int):
        from app.core.errors import error_body

        body = json.dumps(error_body(413, f"Request body exceeds {limit} bytes")).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
