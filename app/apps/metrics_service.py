"""Metrics Aggregation Service (API + aggregation/alert-evaluation worker).

The raw-sample consumer runs separately: ``python -m app.messaging.metric_consumer``.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.alerts import router as alerts_router
from app.api.metric_aggregation import router as aggregation_router
from app.api.metric_query import router as metric_query_router
from app.core.background import PeriodicTask
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.db.session import SessionLocal
from app.services.alerting import evaluate_alerts

SERVICE = "metrics-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)


def _aggregate_and_alert() -> None:
    with SessionLocal() as db:
        evaluate_alerts(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = (PeriodicTask("aggregate-and-alert", settings.aggregation_interval_seconds, _aggregate_and_alert).start()
            if settings.background_workers_enabled else None)
    yield
    if task:
        task.stop()


app = FastAPI(
    title="Metrics Aggregation Service",
    description="Time-bucketed metrics, percentile latency, error rates and threshold alerts.",
    version=settings.app_version,
    lifespan=lifespan,
)
app.include_router(aggregation_router)
app.include_router(metric_query_router)
app.include_router(alerts_router)
app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
