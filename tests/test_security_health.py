import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings
from app.core.logging import redact
from app.core.security import authenticate_user, create_access_token, decode_access_token, sanitize_filter
from tests.conftest import INTERNAL


def test_jwt_roundtrip_expiry_and_tampering():
    token, _ = create_access_token("alice", "analyst")
    assert decode_access_token(token)["role"] == "analyst"
    expired = jwt.encode({"sub": "a", "role": "viewer", "exp": int(time.time()) - 10}, settings.jwt_secret, algorithm="HS256")
    forged = jwt.encode({"sub": "a", "role": "admin", "exp": int(time.time()) + 100}, "other-secret", algorithm="HS256")
    none_alg = jwt.encode({"sub": "a", "role": "admin", "exp": int(time.time()) + 100}, "", algorithm="none")
    for bad in (expired, forged, none_alg, "garbage"):
        with pytest.raises(Exception) as exc:
            decode_access_token(bad)
        assert getattr(exc.value, "status_code", None) == 401


def test_credentials_and_disabled_accounts(monkeypatch):
    assert authenticate_user("viewer", "viewer-pw") == "viewer"
    assert authenticate_user("viewer", "wrong") is None
    monkeypatch.setattr(settings, "console_viewer_password", "")      # empty password disables the account
    assert authenticate_user("viewer", "") is None


def test_security_fails_closed_without_configured_secrets(apps, monkeypatch):
    monkeypatch.setattr(settings, "internal_api_token", "")
    assert TestClient(apps["trace"]).get("/api/v1/traces", headers={"X-Internal-Token": ""}).status_code == 401
    monkeypatch.setattr(settings, "ingestion_api_keys", "")
    assert TestClient(apps["ingestion"]).post("/api/v1/telemetry/logs", json={"events": []},
                                              headers={"X-API-Key": ""}).status_code == 401


def test_sanitize_filter_and_secret_redaction():
    assert sanitize_filter("a\x00b\x1fc") == "abc" and sanitize_filter("   ") is None and len(sanitize_filter("x" * 999)) == 200
    assert "hunter2" not in redact("login password=hunter2 api_key: abc123 ok")
    assert "abc123" not in redact("api_key: abc123")


def test_health_and_readiness(apps, monkeypatch):
    client = TestClient(apps["trace"])
    assert client.get("/health").json() == {"status": "healthy", "service": "trace-service"}
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": "ok"}


def test_readiness_reports_database_failure_without_leaking_details(monkeypatch):
    from app.core import health

    def boom():
        raise RuntimeError("mysql://root:secret@db:3306 unreachable")
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(health.build_health_router("svc", {"database": boom}))
    r = TestClient(app).get("/ready")
    assert r.status_code == 503 and r.json()["checks"] == {"database": "unavailable"}
    assert "secret" not in r.text and TestClient(app).get("/health").status_code == 200


def test_unhandled_errors_return_no_stack_trace(monkeypatch):
    from fastapi import FastAPI
    from app.core.errors import install_error_handlers
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("password=hunter2 at /srv/app/secret.py line 3")
    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and r.json()["error"]["message"] == "Internal server error"
    assert "hunter2" not in r.text and "secret.py" not in r.text


def test_database_failure_surfaces_as_500_without_internals(apps, monkeypatch):
    from app.db import session

    def broken_get_db():
        raise RuntimeError("Can't connect to MySQL server on 'mysql'")
        yield
    apps["trace"].dependency_overrides[session.get_db] = broken_get_db
    try:
        r = TestClient(apps["trace"], raise_server_exceptions=False).get("/api/v1/traces", headers=INTERNAL)
    finally:
        apps["trace"].dependency_overrides.clear()
    assert r.status_code == 500 and "MySQL" not in r.text
