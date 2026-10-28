import logging
import random
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.context import outbound_headers
from app.core.errors import install_error_handlers
from app.core.http_client import make_client
from app.core.health import build_health_router, check_database
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.db.session import get_db
from app.models.payment_attempt import PaymentAttempt
from app.sample_services.scenarios import SCENARIO_HEADER, resolve_scenario
from app.telemetry.instrument import setup_service_telemetry

SERVICE = "payment-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(SERVICE)

app = FastAPI(
    title="Payment Service",
    description="Sample payment service (owns payment_attempts).",
    version=settings.app_version,
)


class PaymentRequest(BaseModel):
    # The order service sends everything needed: this service never reads the
    # order service's database.
    order_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    customer_id: str = Field(min_length=1, max_length=100)


@app.post("/payments")
def process_payment(
    request: PaymentRequest,
    db: Session = Depends(get_db),
    x_test_scenario: str | None = Header(default=None, alias=SCENARIO_HEADER),
):
    scenario = resolve_scenario(x_test_scenario)
    with tracer.start_as_current_span("payment.process") as span:
        span.set_attribute("order.id", request.order_id)
        span.set_attribute("test.scenario", scenario)

        if scenario == "slow_payment":
            logger.warning("Scenario slow_payment: sleeping %ss", settings.slow_payment_seconds)
            time.sleep(settings.slow_payment_seconds)

        if scenario == "payment_failure":
            logger.error("Scenario payment_failure: payment provider error for order %s", request.order_id)
            exc = RuntimeError("Payment provider rejected the transaction")
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise HTTPException(500, "Payment provider error")

        if scenario == "intermittent_unavailability" and random.random() < settings.intermittent_failure_rate:
            logger.error("Scenario intermittent_unavailability: payment backend unavailable")
            span.set_status(trace.Status(trace.StatusCode.ERROR, "payment backend unavailable"))
            raise HTTPException(503, "Payment backend temporarily unavailable")

        if scenario == "invalid_downstream_response":
            logger.error("Scenario invalid_downstream_response: returning a malformed body")
            return JSONResponse({"unexpected": "malformed", "payment_status": None})

        attempt = PaymentAttempt(order_id=request.order_id, amount=request.amount, status="success",
                                 transaction_reference=f"txn-{uuid.uuid4().hex}")
        try:
            db.add(attempt)
            db.commit()
            db.refresh(attempt)
        except Exception as exc:
            db.rollback()
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            logger.exception("Failed to save payment attempt")
            raise HTTPException(500, "Failed to save payment attempt") from exc
        logger.info("Payment recorded: id=%s order_id=%s", attempt.id, attempt.order_id)

        try:
            with make_client("notification", settings.sample_call_timeout_seconds) as client:
                response = client.post(
                    "/notifications",
                    json={"order_id": request.order_id, "channel": "email",
                          "recipient": f"{request.customer_id}@example.test"},
                    headers={**outbound_headers(), SCENARIO_HEADER: scenario},
                )
                response.raise_for_status()
                notification = response.json()
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, type(exc).__name__))
            logger.error("Notification service call failed: %s", type(exc).__name__)
            raise HTTPException(502, "Payment was recorded, but notification failed") from exc

        return {"payment_id": attempt.id, "order_id": request.order_id, "amount": attempt.amount,
                "payment_status": attempt.status, "transaction_reference": attempt.transaction_reference,
                "notification": notification}


app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
setup_service_telemetry(app, SERVICE)
