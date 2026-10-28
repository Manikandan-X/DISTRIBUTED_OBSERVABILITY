"""Authentication / authorisation primitives.

* Telemetry producers authenticate with an API key (``X-API-Key``).
* Console users authenticate at the gateway with a JWT.
* Internal services only trust callers that present ``X-Internal-Token``
  (the gateway/query/rca services hold it); the gateway forwards the
  already-verified role in ``X-User-Role``.

All comparisons are constant-time and every check fails *closed*: if a secret
is not configured the request is refused.
"""

import hmac
import logging
import re
import time

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

ROLE_ORDER = {"viewer": 1, "analyst": 2, "admin": 3}
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- internal
def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    expected = settings.internal_api_token
    if not expected or not x_internal_token or not _eq(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing internal credentials")


def current_role(x_user_role: str | None = Header(default=None)) -> str:
    """Role forwarded by the gateway (defaults to the least privileged)."""
    return x_user_role if x_user_role in ROLE_ORDER else "viewer"


def require_role(minimum: str):
    def _check(role: str = Depends(current_role)) -> str:
        if ROLE_ORDER[role] < ROLE_ORDER[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"The '{minimum}' role is required")
        return role

    return _check


# --------------------------------------------------------------- telemetry
def _ingestion_keys() -> list[str]:
    return [k.strip() for k in settings.ingestion_api_keys.split(",") if k.strip()]


def require_ingestion_key(x_api_key: str | None = Header(default=None)) -> None:
    keys = _ingestion_keys()
    if not keys or not x_api_key or not any(_eq(x_api_key, k) for k in keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


# --------------------------------------------------------------------- JWT
def _console_users() -> dict[str, tuple[str, str]]:
    users = {}
    for user, password, role in (
        (settings.console_admin_user, settings.console_admin_password, "admin"),
        (settings.console_analyst_user, settings.console_analyst_password, "analyst"),
        (settings.console_viewer_user, settings.console_viewer_password, "viewer"),
    ):
        if user and password:  # an empty password disables the account
            users[user] = (password, role)
    return users


def authenticate_user(username: str, password: str) -> str | None:
    """Return the role for valid credentials, otherwise None."""
    record = _console_users().get(username)
    if record is None:
        # Burn comparable time so unknown users are not distinguishable.
        _eq(password, "x" * 16)
        return None
    return record[1] if _eq(password, record[0]) else None


def create_access_token(username: str, role: str) -> tuple[str, int]:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is not configured")
    ttl = settings.jwt_ttl_minutes * 60
    now = int(time.time())
    token = jwt.encode(
        {"sub": username, "role": role, "iat": now, "exp": now + ttl},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, ttl


def decode_access_token(token: str) -> dict:
    if not settings.jwt_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                            options={"require": ["exp", "sub", "role"]})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    if claims.get("role") not in ROLE_ORDER:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token role")
    return claims


# ----------------------------------------------------------------- sanitise
def sanitize_filter(value: str | None, max_length: int = 200) -> str | None:
    """Make a user-supplied filter value safe to use.

    Values are always bound as query parameters (never concatenated into SQL)
    and LIKE wildcards are escaped by the caller; here we additionally drop
    control characters and bound the length.
    """
    if value is None:
        return None
    cleaned = _CONTROL_CHARS_RE.sub("", value).strip()[:max_length]
    return cleaned or None
