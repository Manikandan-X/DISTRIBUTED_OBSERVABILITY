"""Root-Cause Analysis Service."""

from fastapi import FastAPI

from app.api.root_cause_analysis import router as rca_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware

SERVICE = "rca-service"
settings.service_name = SERVICE
configure_logging()

app = FastAPI(
    title="Root-Cause Analysis Service",
    description="Deterministic, evidence-based diagnostics for failed or slow traces.",
    version=settings.app_version,
)
app.include_router(rca_router)
app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
