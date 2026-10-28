import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.notification_attempt import NotificationAttempt
from app.models.order import Order
from app.models.payment_attempt import PaymentAttempt
from tests.conftest import _asgi_transport, failing_transport

ORDER = {"order_number": "ORD-1", "customer_id": "cust1", "amount": 25.5}


@pytest.fixture
def stack(wire):
    from app.sample_services.notification_service import app as notification
    from app.sample_services.order_service import app as order
    from app.sample_services.payment_service import app as payment
    wire(payment=_asgi_transport(payment), notification=_asgi_transport(notification))
    return TestClient(order, raise_server_exceptions=False), wire


def place(client, scenario=None, number="ORD-1"):
    headers = {"X-Test-Scenario": scenario} if scenario else {}
    return client.post("/orders", json={**ORDER, "order_number": number}, headers=headers)


def test_normal_request_flows_order_payment_notification(stack):
    client, _ = stack
    r = place(client)
    assert r.status_code == 200 and r.json()["order_status"] == "paid"
    assert r.json()["payment"]["notification"]["status"] == "sent"
    with SessionLocal() as db:
        assert db.query(Order).one().status == "paid"
        assert db.query(PaymentAttempt).count() == 1 and db.query(NotificationAttempt).count() == 1


def test_payment_does_not_read_the_order_database(stack):
    client, _ = stack
    place(client)
    from app.sample_services.payment_service import PaymentRequest
    assert set(PaymentRequest.model_fields) == {"order_id", "amount", "customer_id"}     # everything arrives in the request


@pytest.mark.parametrize("scenario", ["payment_failure", "invalid_downstream_response"])
def test_backend_generated_failures_surface_as_502_and_order_is_marked(stack, scenario):
    client, _ = stack
    r = place(client, scenario)
    assert r.status_code == 502
    with SessionLocal() as db:
        assert db.query(Order).one().status == "payment_failed"


def test_slow_payment_still_succeeds_but_sleeps(stack, monkeypatch):
    import time
    client, _ = stack
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    assert place(client, "slow_payment").status_code == 200
    assert slept and slept[0] == pytest.approx(0.01)


def test_notification_timeout_scenario_hangs_notification_and_payment_reports_502(stack, monkeypatch):
    import time
    client, wire = stack
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    from app.sample_services.notification_service import app as notification
    direct = TestClient(notification)
    assert direct.post("/notifications", json={"order_id": 1, "channel": "email", "recipient": "a@b.c"},
                       headers={"X-Test-Scenario": "notification_timeout"}).status_code == 200
    assert slept, "notification must hang in this scenario"
    wire(notification=failing_transport("timeout"))                       # caller's timeout fires
    assert place(client, "notification_timeout", "ORD-2").status_code == 502


def test_intermittent_unavailability(stack, monkeypatch):
    import random
    client, _ = stack
    monkeypatch.setattr(random, "random", lambda: 0.0)
    assert place(client, "intermittent_unavailability", "A").status_code == 502
    monkeypatch.setattr(random, "random", lambda: 0.99)
    assert place(client, "intermittent_unavailability", "B").status_code == 200


def test_payment_service_down_and_duplicate_order(stack):
    client, wire = stack
    wire(payment=failing_transport("connect"))
    assert place(client).status_code == 502
    assert place(client).status_code == 409


def test_scenario_header_can_be_disabled_and_default_is_configurable(stack, monkeypatch):
    from app.core.config import settings
    client, _ = stack
    monkeypatch.setattr(settings, "allow_scenario_header", False)
    assert place(client, "payment_failure").status_code == 200            # header ignored
    monkeypatch.setattr(settings, "default_failure_scenario", "payment_failure")
    assert place(client, None, "ORD-9").status_code == 502                # controlled test configuration


def test_invalid_order_payload_is_422(stack):
    client, _ = stack
    assert client.post("/orders", json={"order_number": "", "customer_id": "c", "amount": -1}).status_code == 422
