"""Trace Processing Service (read API + trace completion worker).

The span consumer runs as a separate process: ``python -m app.messaging.trace_consumer``.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import router as dependencies_router
from app.api.traces import router as traces_router
from app.core.background import PeriodicTask
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.db.session import SessionLocal
from app.services.trace_completion import finalize_traces

SERVICE = "trace-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)


def _finalize() -> None:
    with SessionLocal() as db:
        finalize_traces(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = PeriodicTask("trace-completion", 10, _finalize).start() if settings.background_workers_enabled else None
    yield
    if task:
        task.stop()


app = FastAPI(
    title="Trace Processing Service",
    description="Reconstructed distributed traces, span timelines and service dependencies.",
    version=settings.app_version,
    lifespan=lifespan,
)
app.include_router(traces_router)
app.include_router(dependencies_router)
app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
