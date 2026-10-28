"""Observability Query Service."""

from fastapi import FastAPI

from app.api.observability_query import router as query_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware

SERVICE = "query-service"
settings.service_name = SERVICE
configure_logging()

app = FastAPI(
    title="Observability Query Service",
    description="Frontend-facing queries composed from the trace, log, metrics and RCA services.",
    version=settings.app_version,
)
app.include_router(query_router)
app.include_router(build_health_router(SERVICE))  # no database: nothing local to check
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
