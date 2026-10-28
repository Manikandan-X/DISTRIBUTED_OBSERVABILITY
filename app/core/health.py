"""Liveness (/health) and readiness (/ready) endpoints."""

import logging
from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)


def check_database() -> None:
    from app.db import session

    with session.engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def check_broker() -> None:
    import pika

    params = pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        credentials=pika.PlainCredentials(settings.rabbitmq_default_user, settings.rabbitmq_default_pass),
        socket_timeout=3,
        blocked_connection_timeout=3,
        connection_attempts=1,
    )
    conn = pika.BlockingConnection(params)
    conn.close()


def build_health_router(service_name: str, checks: dict[str, Callable[[], None]] | None = None) -> APIRouter:
    router = APIRouter(tags=["Health"])
    checks = checks or {}

    @router.get("/health")
    def health():
        """Liveness: the process is running."""
        return {"status": "healthy", "service": service_name}

    @router.get("/ready")
    def ready():
        """Readiness: dependencies this service needs are reachable."""
        results, ok = {}, True
        for name, check in checks.items():
            try:
                check()
                results[name] = "ok"
            except Exception:
                # Details stay in the log, not in the response.
                logger.exception("Readiness check failed: %s", name)
                results[name] = "unavailable"
                ok = False
        body = {"status": "ready" if ok else "not_ready", "service": service_name, "checks": results}
        return JSONResponse(status_code=200 if ok else 503, content=body)

    return router
