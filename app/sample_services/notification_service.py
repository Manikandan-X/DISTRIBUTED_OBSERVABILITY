import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.db.session import get_db
from app.models.notification_attempt import NotificationAttempt
from app.sample_services.scenarios import SCENARIO_HEADER, resolve_scenario
from app.telemetry.instrument import setup_service_telemetry

SERVICE = "notification-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(SERVICE)

app = FastAPI(
    title="Notification Service",
    description="Sample notification service (owns notification_attempts).",
    version=settings.app_version,
)


class NotificationRequest(BaseModel):
    order_id: int = Field(gt=0)
    channel: str = Field(min_length=1, max_length=30)
    recipient: str = Field(min_length=1, max_length=150)


@app.post("/notifications")
def send_notification(
    request: NotificationRequest,
    db: Session = Depends(get_db),
    x_test_scenario: str | None = Header(default=None, alias=SCENARIO_HEADER),
):
    scenario = resolve_scenario(x_test_scenario)
    with tracer.start_as_current_span("notification.send") as span:
        span.set_attribute("order.id", request.order_id)
        span.set_attribute("notification.channel", request.channel)
        span.set_attribute("test.scenario", scenario)

        if scenario == "notification_timeout":
            logger.warning("Scenario notification_timeout: hanging for %ss", settings.notification_timeout_seconds)
            time.sleep(settings.notification_timeout_seconds)

        attempt = NotificationAttempt(order_id=request.order_id, channel=request.channel,
                                      recipient=request.recipient, status="sent", error_message=None)
        try:
            db.add(attempt)
            db.commit()
            db.refresh(attempt)
        except Exception as exc:
            db.rollback()
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            logger.exception("Failed to save notification attempt")
            raise HTTPException(500, "Failed to save notification attempt") from exc

        logger.info("Notification sent: id=%s order_id=%s", attempt.id, attempt.order_id)
        return {"notification_id": attempt.id, "order_id": attempt.order_id,
                "channel": attempt.channel, "status": attempt.status}


app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
setup_service_telemetry(app, SERVICE)
