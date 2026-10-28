"""Telemetry Ingestion Service."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ingestion import router as ingestion_router
from app.core.background import PeriodicTask
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_broker, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.db.session import SessionLocal
from app.services.ingestion import relay_failed_events

SERVICE = "ingestion-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)


def _relay() -> None:
    with SessionLocal() as db:
        relay_failed_events(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = PeriodicTask("outbox-relay", 15, _relay).start() if settings.background_workers_enabled else None
    yield
    if task:
        task.stop()


app = FastAPI(
    title="Telemetry Ingestion Service",
    description="Validates telemetry and publishes it to RabbitMQ (at-least-once).",
    version=settings.app_version,
    lifespan=lifespan,
)
app.include_router(ingestion_router)
app.include_router(build_health_router(SERVICE, {"database": check_database, "broker": check_broker}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
