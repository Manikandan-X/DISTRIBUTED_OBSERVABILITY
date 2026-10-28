"""API Gateway: the single entry point for the console and telemetry producers.

Responsibilities: authentication (JWT) and role checks, request validation and
size limits, correlation-ID and trace-context propagation, per-request
timeouts, consistent errors, and gateway-level request metadata (logs + metrics
+ traces). It contains NO business logic.

Error origin is always explicit:
* errors created here      -> ``X-Error-Source: gateway``,    body ``error.source == "gateway"``
* errors from a downstream -> ``X-Error-Source: downstream``, body ``error.source == "<service>"``
"""

import logging
import re
import time

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.context import CORRELATION_HEADER, get_correlation_id
from app.core.errors import ApiError, install_error_handlers
from app.core.health import build_health_router
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, MaxBodySizeMiddleware
from app.core.http_client import SERVICE_URLS, TRANSPORT_OVERRIDES
from app.core.security import (
    ROLE_ORDER,
    authenticate_user,
    create_access_token,
    decode_access_token,
)
from app.telemetry.instrument import setup_service_telemetry

SERVICE = "api-gateway"
settings.service_name = SERVICE
configure_logging()
logger = logging.getLogger("gateway.access")

SERVICE_LABELS = {"ingestion": "ingestion-service", "query": "query-service", "order": "order-service"}

# (methods, path regex, target service, rewritten path or None, auth, minimum role)
#   auth: "jwt" | "api_key"
ROUTES: list[tuple[set[str], str, str, str | None, str, str]] = [
    ({"POST"}, r"^/api/v1/telemetry(/(logs|traces|metrics|batch))?$", "ingestion", None, "api_key", "viewer"),
    ({"GET"}, r"^/api/v1/telemetry/stats$", "ingestion", None, "jwt", "analyst"),
    ({"POST"}, r"^/api/v1/telemetry/retry-failed$", "ingestion", None, "jwt", "admin"),
    ({"POST"}, r"^/api/v1/sample/orders$", "order", "/orders", "jwt", "analyst"),
    ({"GET"}, r"^/api/v1/sample/scenarios$", "order", "/scenarios", "jwt", "viewer"),
    # log and diagnostic data need the analyst role (also enforced again downstream)
    ({"GET"}, r"^/api/v1/(logs|diagnostics)(/.*)?$", "query", None, "jwt", "analyst"),
    ({"GET"}, r"^/api/v1/traces/[^/]+/logs$", "query", None, "jwt", "analyst"),
    ({"GET"}, r"^/api/v1/(traces|logs|metrics|dependencies|diagnostics|alerts|overview|services)(/.*)?$",
     "query", None, "jwt", "viewer"),
    ({"POST", "PATCH", "PUT"}, r"^/api/v1/(diagnostics|alerts|metrics)(/.*)?$", "query", None, "jwt", "analyst"),
]
_COMPILED = [(m, re.compile(p), t, rw, a, r) for m, p, t, rw, a, r in ROUTES]

FORWARD_HEADERS = {"content-type", "accept", "x-api-key"}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


app = FastAPI(
    title="Observability API Gateway",
    description="Single entry point: authentication, routing, timeouts and consistent errors.",
    version=settings.app_version,
)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@auth_router.post("/login", response_model=TokenResponse, summary="Obtain a console access token")
def login(request: LoginRequest):
    role = authenticate_user(request.username, request.password)
    if role is None:
        raise ApiError(401, "Invalid username or password", code="invalid_credentials", source=SERVICE)
    try:
        token, ttl = create_access_token(request.username, role)
    except RuntimeError as exc:
        logger.error("Token issuance is not configured")
        raise ApiError(503, "Authentication is not configured", source=SERVICE) from exc
    logger.info("Console login succeeded: user=%s role=%s", request.username, role)
    return TokenResponse(access_token=token, expires_in=ttl, role=role)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "Authentication required", code="unauthorized", source=SERVICE,
                       headers={"WWW-Authenticate": "Bearer"})
    return token


@auth_router.get("/me", summary="Current user")
def me(request: Request):
    claims = decode_access_token(_bearer(request))
    return {"username": claims["sub"], "role": claims["role"]}


app.include_router(auth_router)


def _gateway_error(status: int, message: str, code: str | None = None) -> JSONResponse:
    from app.core.errors import error_body

    return JSONResponse(error_body(status, message, code, source=SERVICE), status_code=status,
                        headers={"X-Error-Source": "gateway"})


def _downstream_error(status: int, message: str, code: str, service: str) -> JSONResponse:
    from app.core.errors import error_body

    return JSONResponse(error_body(status, message, code, source=SERVICE_LABELS.get(service, service)),
                        status_code=status,
                        headers={"X-Error-Source": "downstream", "X-Downstream-Service": service})


def _match(method: str, path: str):
    matched_path = False
    for methods, pattern, target, rewrite, auth, role in _COMPILED:
        if pattern.match(path):
            matched_path = True
            if method in methods:
                return target, rewrite, auth, role, True
    return None, None, None, None, matched_path


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
async def proxy(request: Request, path: str):
    started = time.perf_counter()
    full_path = request.url.path
    target, rewrite, auth, min_role, found = _match(request.method, full_path)
    user, role = "anonymous", None
    response: Response

    if target is None:
        response = _gateway_error(405 if found else 404,
                                  "Method not allowed" if found else "Route not found")
    else:
        try:
            if auth == "jwt":
                claims = decode_access_token(_bearer(request))
                user, role = claims["sub"], claims["role"]
                if ROLE_ORDER[role] < ROLE_ORDER[min_role]:
                    raise ApiError(403, f"The '{min_role}' role is required", source=SERVICE)
            response = await _forward(request, target, rewrite or full_path, user, role)
        except HTTPException as exc:  # includes ApiError and auth failures from the security module
            response = _gateway_error(exc.status_code, str(exc.detail), getattr(exc, "error_code", None))
            for k, v in (exc.headers or {}).items():
                response.headers[k] = v
        except Exception:
            logger.exception("Gateway failure while handling %s %s", request.method, full_path)
            response = _gateway_error(500, "Internal gateway error")

    duration_ms = (time.perf_counter() - started) * 1000
    # Gateway-level request metadata (also shipped to telemetry as an INFO log).
    logger.info("%s %s -> %s in %.1fms target=%s user=%s role=%s",
                request.method, full_path, response.status_code, duration_ms, target or "none", user, role or "-",
                extra={"http_method": request.method, "http_path": full_path, "http_status": response.status_code,
                       "duration_ms": round(duration_ms, 2), "target": target or "none", "user": user})
    return response


async def _forward(request: Request, target: str, path: str, user: str, role: str | None) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_HEADERS}
    if request.headers.get("x-test-scenario") and target == "order":
        headers["X-Test-Scenario"] = request.headers["x-test-scenario"]
    headers["X-Internal-Token"] = settings.internal_api_token
    headers[CORRELATION_HEADER] = get_correlation_id() or ""
    if role:
        headers["X-User-Role"], headers["X-User-Name"] = role, user

    body = await request.body()
    try:
        async with httpx.AsyncClient(base_url=SERVICE_URLS[target](), timeout=settings.gateway_timeout_seconds,
                                     transport=TRANSPORT_OVERRIDES.get(target)) as client:
            upstream = await client.request(request.method, path, params=request.query_params,
                                            content=body, headers=headers)
    except httpx.TimeoutException:
        return _downstream_error(504, f"{SERVICE_LABELS[target]} did not respond in time",
                                 "downstream_timeout", target)
    except httpx.TransportError:
        return _downstream_error(503, f"{SERVICE_LABELS[target]} is unavailable",
                                 "downstream_unavailable", target)

    out = Response(content=upstream.content, status_code=upstream.status_code,
                   media_type=upstream.headers.get("content-type"))
    if upstream.status_code >= 400:
        out.headers["X-Error-Source"] = "downstream"
        out.headers["X-Downstream-Service"] = target
    return out


async def _check_downstream(name: str) -> None:
    async with httpx.AsyncClient(base_url=SERVICE_URLS[name](), timeout=2.0,
                                 transport=TRANSPORT_OVERRIDES.get(name)) as client:
        (await client.get("/health")).raise_for_status()


health_router = build_health_router(SERVICE)
# Replace the generic /ready with one that probes the services the gateway routes to.
health_router.routes[:] = [r for r in health_router.routes if getattr(r, "path", "") != "/ready"]


@health_router.get("/ready", tags=["Health"])
async def ready():
    results, ok = {}, True
    for name in ("query", "ingestion"):
        try:
            await _check_downstream(name)
            results[SERVICE_LABELS[name]] = "ok"
        except Exception:
            results[SERVICE_LABELS[name]] = "unavailable"
            ok = False
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "not_ready", "service": SERVICE, "checks": results})


app.include_router(health_router)
install_error_handlers(app)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
setup_service_telemetry(app, SERVICE)
