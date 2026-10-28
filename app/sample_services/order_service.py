import logging

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
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
from app.models.order import Order
from app.sample_services.scenarios import SCENARIO_HEADER, SCENARIOS, resolve_scenario
from app.telemetry.instrument import setup_service_telemetry

SERVICE = "order-service"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(SERVICE)

app = FastAPI(
    title="Order Service",
    description="Sample order service (owns orders). Calls Payment, which calls Notification.",
    version=settings.app_version,
)


class OrderRequest(BaseModel):
    order_number: str = Field(min_length=1, max_length=50)
    customer_id: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)


@app.get("/scenarios")
def list_scenarios():
    return {"scenarios": SCENARIOS, "default": settings.default_failure_scenario}


def _valid_payment(body) -> bool:
    return (isinstance(body, dict) and body.get("payment_status") == "success"
            and isinstance(body.get("transaction_reference"), str))


@app.post("/orders")
def create_order(
    request: OrderRequest,
    db: Session = Depends(get_db),
    x_test_scenario: str | None = Header(default=None, alias=SCENARIO_HEADER),
):
    scenario = resolve_scenario(x_test_scenario)
    with tracer.start_as_current_span("order.create") as span:
        span.set_attribute("order.number", request.order_number)
        span.set_attribute("order.amount", request.amount)
        span.set_attribute("test.scenario", scenario)

        if db.query(Order).filter(Order.order_number == request.order_number).first() is not None:
            raise HTTPException(409, "Order number already exists")

        order = Order(order_number=request.order_number, customer_id=request.customer_id,
                      amount=request.amount, status="pending")
        try:
            db.add(order)
            db.commit()
            db.refresh(order)
        except Exception as exc:
            db.rollback()
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            logger.exception("Failed to save order")
            raise HTTPException(500, "Failed to save order") from exc
        logger.info("Order created: id=%s number=%s scenario=%s", order.id, order.order_number, scenario)

        def fail(status: int, detail: str, exc: Exception | None = None):
            order.status = "payment_failed"
            db.commit()
            if exc is not None:
                span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, detail))
            logger.error("%s (order_id=%s)", detail, order.id)
            raise HTTPException(status, detail) from exc

        try:
            with make_client("payment", settings.sample_call_timeout_seconds + 4) as client:
                response = client.post(
                    "/payments",
                    json={"order_id": order.id, "amount": order.amount, "customer_id": order.customer_id},
                    headers={**outbound_headers(), SCENARIO_HEADER: scenario},
                )
        except httpx.TimeoutException as exc:
            fail(504, "Payment service timed out", exc)
        except httpx.HTTPError as exc:
            fail(502, "Payment service unreachable", exc)

        if response.status_code >= 500:
            fail(502, f"Payment service failed with HTTP {response.status_code}")
        try:
            payment = response.json()
        except ValueError as exc:
            fail(502, "Payment service returned a non-JSON response", exc)
        if response.status_code >= 400 or not _valid_payment(payment):
            fail(502, "Payment service returned an invalid response")

        order.status = "paid"
        db.commit()
        return {"order_id": order.id, "order_number": order.order_number, "customer_id": order.customer_id,
                "amount": order.amount, "order_status": order.status, "payment": payment}


app.include_router(build_health_router(SERVICE, {"database": check_database}))
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
setup_service_telemetry(app, SERVICE)
