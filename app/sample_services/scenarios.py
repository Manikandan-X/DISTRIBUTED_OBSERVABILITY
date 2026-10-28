"""Controlled failure scenarios for the sample application.

Failures are produced by the *backend* sample services, never by the
frontend. A scenario is chosen per request with the ``X-Test-Scenario``
header (forwarded Order -> Payment -> Notification) or globally with the
``DEFAULT_FAILURE_SCENARIO`` environment variable.
"""

from app.core.config import settings

SCENARIO_HEADER = "X-Test-Scenario"

SCENARIOS = {
    "normal": "Everything succeeds.",
    "slow_payment": "Payment service responds slowly (SLOW_PAYMENT_SECONDS).",
    "payment_failure": "Payment service returns HTTP 500.",
    "notification_timeout": "Notification service hangs longer than the caller's timeout.",
    "invalid_downstream_response": "Payment service returns HTTP 200 with a malformed body.",
    "intermittent_unavailability": "Payment service returns HTTP 503 for a share of requests (INTERMITTENT_FAILURE_RATE).",
}


def resolve_scenario(header_value: str | None) -> str:
    candidate = (header_value or "").strip().lower() if settings.allow_scenario_header else ""
    if candidate in SCENARIOS:
        return candidate
    default = settings.default_failure_scenario.strip().lower()
    return default if default in SCENARIOS else "normal"
