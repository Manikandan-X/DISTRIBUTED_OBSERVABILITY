"""Log Processing Service (read API). The consumer is a separate process."""

from fastapi import FastAPI

from app.api.logs import router as logs_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware

SERVICE = "log-service"
settings.service_name = SERVICE
configure_logging()

app = FastAPI(
    title="Log Processing Service",
    description="Normalised, searchable logs linked to traces.",
    version=settings.app_version,
)
app.include_router(logs_router)
app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
