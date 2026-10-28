"""Resilient HTTP client for service-to-service calls.

* explicit timeout on every call
* bounded retries with exponential backoff (idempotent GETs only)
* typed errors so callers can degrade gracefully (partial results)
"""

import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.context import outbound_headers

logger = logging.getLogger(__name__)

# Tests (or alternative deployments) can inject a transport per service.
TRANSPORT_OVERRIDES: dict[str, httpx.BaseTransport] = {}

SERVICE_URLS = {
    "ingestion": lambda: settings.ingestion_service_url,
    "trace": lambda: settings.trace_service_url,
    "log": lambda: settings.log_service_url,
    "metrics": lambda: settings.metrics_service_url,
    "rca": lambda: settings.rca_service_url,
    "query": lambda: settings.query_service_url,
    "order": lambda: settings.order_service_url,
    "payment": lambda: settings.payment_service_url,
    "notification": lambda: settings.notification_service_url,
}


class DownstreamError(Exception):
    """A downstream service call failed.

    ``kind`` is one of: timeout, unavailable, http_error, bad_response.
    """

    def __init__(self, service: str, kind: str, message: str, status_code: int | None = None):
        super().__init__(f"{service}: {kind}: {message}")
        self.service = service
        self.kind = kind
        self.message = message
        self.status_code = status_code


class DownstreamClient:
    def __init__(self, service: str, timeout: float | None = None,
                 max_attempts: int | None = None, backoff: float | None = None):
        if service not in SERVICE_URLS:
            raise ValueError(f"Unknown downstream service: {service}")
        self.service = service
        self.timeout = timeout or settings.downstream_timeout_seconds
        self.max_attempts = max_attempts or settings.downstream_max_attempts
        self.backoff = settings.downstream_backoff_seconds if backoff is None else backoff

    def _headers(self) -> dict[str, str]:
        headers = {"X-Internal-Token": settings.internal_api_token, **outbound_headers()}
        return headers

    def request(self, method: str, path: str, params: dict | None = None,
                json_body: Any = None, role: str | None = None) -> Any:
        params = clean_params(params) if params else None  # never send 'x=' for None values
        headers = self._headers()
        if role:
            headers["X-User-Role"] = role
        attempts = self.max_attempts if method.upper() == "GET" else 1
        last: DownstreamError | None = None

        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(
                    base_url=SERVICE_URLS[self.service](),
                    timeout=self.timeout,
                    transport=TRANSPORT_OVERRIDES.get(self.service),
                ) as client:
                    response = client.request(method, path, params=params,
                                              json=json_body, headers=headers)
            except httpx.TimeoutException as exc:
                last = DownstreamError(self.service, "timeout", type(exc).__name__)
            except httpx.TransportError as exc:
                last = DownstreamError(self.service, "unavailable", type(exc).__name__)
            else:
                if response.status_code >= 500:
                    last = DownstreamError(self.service, "http_error",
                                           f"HTTP {response.status_code}", response.status_code)
                elif response.status_code >= 400:
                    # Client errors are definitive: never retried.
                    raise DownstreamError(self.service, "http_error",
                                          _error_message(response), response.status_code)
                else:
                    try:
                        return response.json()
                    except ValueError:
                        raise DownstreamError(self.service, "bad_response",
                                              "Response was not valid JSON", response.status_code)

            if attempt < attempts:
                delay = self.backoff * (2 ** (attempt - 1))
                logger.warning("Retrying %s %s%s (attempt %s/%s) after %s",
                               method, self.service, path, attempt, attempts, last.kind)
                time.sleep(delay)

        assert last is not None
        raise last

    def get(self, path: str, params: dict | None = None, role: str | None = None):
        return self.request("GET", path, params=params, role=role)

    def post(self, path: str, json_body: Any = None, params: dict | None = None, role: str | None = None):
        return self.request("POST", path, params=params, json_body=json_body, role=role)

    def patch(self, path: str, json_body: Any = None, role: str | None = None):
        return self.request("PATCH", path, json_body=json_body, role=role)


def make_client(service: str, timeout: float) -> httpx.Client:
    """Plain HTTP client for a peer service (used by the sample application)."""
    return httpx.Client(base_url=SERVICE_URLS[service](), timeout=timeout,
                        transport=TRANSPORT_OVERRIDES.get(service))


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except Exception:
        return f"HTTP {response.status_code}"


def clean_params(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}
