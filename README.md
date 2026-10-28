# Distributed Observability & Root-Cause Analysis Platform: backend update

This package contains **only the files that changed or were added** (backend only, no frontend).
Copy them over your existing project folder, keeping the paths. Nothing needs to be deleted.

* **47 files modified**, **70 files added**, 13 files untouched.
* 139 automated tests are included and pass (`pytest`).

---

## 1. What I found in your project

Your upload was a single FastAPI app sharing one database, plus three consumers and three sample services. Compared with the task document:

| Requirement | State in your upload | What I did |
|---|---|---|
| Database tables / Alembic | Nothing created the tables; `alembic/` was mounted in compose but did not exist; the Dockerfile copied a `tests/` folder that did not exist (**the image build would fail**) | Added Alembic (one migration branch per service), a `migrate` container, a `tests/` folder |
| 7 independent services | Only ingestion + sample services; no gateway, no separate trace/log/metrics/RCA/query services | Added **API Gateway, Ingestion, Trace, Log, Metrics, RCA, Query** services (separate processes/containers) |
| Separate database per service | One shared DB; RCA/query read other services' tables | One database per service (`obs_traces`, `obs_logs`, ...); cross-service reads go through HTTP APIs |
| Ingestion endpoints | Only `POST /api/v1/telemetry` | `/logs`, `/traces`, `/metrics`, `/batch`, `/stats`; payload validated before the broker; broker outage handled with an outbox + relay |
| Sample app telemetry to Ingestion | Spans went straight to RabbitMQ; no logs or metrics were sent | Spans, logs **and** metrics go to the Ingestion Service over HTTP |
| Trace processing | Basic span storage | Completion policy, incomplete traces / missing parents, out-of-order and duplicate handling, slow/failed span flags, latency contribution per service |
| Log processing | Basic storage | Severity normalisation, correlation-ID search, duplicate suppression (by id **and** content), repeated-error patterns, trace linking |
| Metrics | Manual aggregation only, one alert type | Automatic time buckets, avg/p50/p90/p95/p99, error rate, throughput, missing-interval gaps, four alert types |
| Alerts | One threshold; acknowledged alerts re-fired as duplicates | Four configurable types, de-duplication, cooldown, auto-resolve, trace evidence, `PATCH /alerts/{id}` |
| Root-cause analysis | "first failed span" only | Deterministic ranked rules, confirmed vs potential, no root cause claimed on weak evidence, evidence table |
| API paths | `/api/v1/observability/...` | The paths from the task document |
| Auth / security | None | JWT login + roles at the gateway, API keys for telemetry, internal token between services, size limits, no stack traces |
| Failure scenarios | Always succeeded | Six backend-generated scenarios |
| Tests | None | 139 pytest tests (unit, integration, failure, API, end-to-end) |

---

## 2. Architecture after the update

```
 console / curl --> api-gateway :8001 --> query-service :8015 -+-> trace-service   :8011  (obs_traces)
   (JWT)             |  (auth, roles,                          +-> log-service     :8012  (obs_logs)
                     |   timeouts)                             +-> metrics-service :8013  (obs_metrics)
                     |                                         +-> rca-service     :8014  (obs_rca) -> calls trace/log/metrics over HTTP
                     +-> ingestion-service :8010 (obs_ingestion) --> RabbitMQ --> trace / log / metric consumers
                     +-> order-service :8002 -> payment-service :8003 -> notification-service :8004
                                   (own DBs: obs_orders / obs_payments / obs_notifications)

 gateway + sample services send spans, logs and metrics over HTTP to ingestion-service
```

Host ports: gateway `8001` (the port your old `backend` used), order `8002`, payment `8003`, notification `8004`, ingestion `8010`, trace `8011`, log `8012`, metrics `8013`, rca `8014`, query `8015`, MySQL `3308`, RabbitMQ `5673` (UI `15673`). Swagger for each service: `http://localhost:<port>/docs`.

---

## 3. How to apply this patch

1. Unzip over your project root (the folder containing `app/`, `Dockerfile`, `docker-compose.yml`). Files use the same relative paths.
2. `cp .env.example .env` and change every `change_me` value.
3. Start everything:
   ```bash
   docker compose down          # old stack (add -v only if you do NOT need the old data)
   docker compose up --build
   ```
   The one-shot `migrate` container creates the databases and applies the migrations first; every other container waits for it. The old `observability_db` is **not** migrated: data from the old single-database layout is not carried over.
4. `app/messaging/otel_rabbitmq_exporter.py` is no longer used (spans go through the Ingestion Service now). I left it in place; you can delete it.

### Try it

```bash
# 1. log in (roles admin / analyst / viewer; passwords from .env)
TOKEN=$(curl -s localhost:8001/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"analyst","password":"analyst_password_change_me"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. generate a real distributed trace through the gateway (the scenario header is optional)
curl -s localhost:8001/api/v1/sample/orders -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H 'X-Test-Scenario: payment_failure' -d '{"order_number":"ORD-1","customer_id":"c1","amount":25}'

# 3. look at it (wait a few seconds; traces are finalised after TRACE_COMPLETION_WAIT_SECONDS)
curl -s "localhost:8001/api/v1/traces?status=error" -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8001/api/v1/diagnostics/analyze/<trace_id> -H "Authorization: Bearer $TOKEN"
curl -s localhost:8001/api/v1/dependencies -H "Authorization: Bearer $TOKEN"
```

Scenarios: `normal`, `slow_payment`, `payment_failure`, `notification_timeout`, `invalid_downstream_response`, `intermittent_unavailability` (header `X-Test-Scenario`, or `DEFAULT_FAILURE_SCENARIO` in `.env`).

Send your own telemetry: `POST /api/v1/telemetry/batch` with header `X-API-Key: <one of INGESTION_API_KEYS>` and body
`{"events":[{"event_type":"log","service_name":"my-app","payload":{"message":"hi","severity":"INFO"}}]}`.

### Run the tests
```bash
pip install -r requirements.txt
pytest -q          # or: docker compose run --rm --no-deps api-gateway pytest -q
```
The tests use in-memory SQLite and in-process service wiring, so they need no MySQL or RabbitMQ.

---

## 4. Modified files (47)

| File | What changed |
|---|---|
| `Dockerfile` | Copies `alembic/`, `alembic.ini`, `tests/`; default command is the API Gateway (`app.main`). |
| `app/api/alerts.py` | Added `PATCH /{id}`, rules endpoints, severity/trace evidence, roles. `/acknowledge` and `/resolve` kept. |
| `app/api/ingestion.py` | Added `/logs`, `/traces`, `/metrics`, `/batch`, `/stats`, `/retry-failed`; API-key auth; per-event validation; legacy `POST /api/v1/telemetry` kept. |
| `app/api/metric_aggregation.py` | Admin-only; internal-token protected. |
| `app/api/metric_query.py` | Added `/services`, `/summary`, `/timeseries`, `/latency` next to `/aggregates`. |
| `app/api/observability_query.py` | Rewritten as the **Query Service** router (no DB; calls the owning services over HTTP; partial results + warnings; role checks). |
| `app/api/root_cause_analysis.py` | Added `POST /diagnostics/analyze/{trace_id}`, `GET /diagnostics`, `GET /diagnostics/{id}`; old `/traces/{id}/analyze` kept as alias. |
| `app/core/config.py` | Every setting is now an env variable: per-service DB name, service URLs, secrets, timeouts, thresholds, RCA weights, scenarios. |
| `app/core/otel.py` | Spans are exported to the **Ingestion Service over HTTP** instead of straight to RabbitMQ. |
| `app/db/base.py` | Registers the new `AlertRule` model. |
| `app/db/session.py` | DB URL built safely (special characters in passwords), DB name from `MYSQL_DATABASE`, SQLite support for tests. |
| `app/main.py` | Now just exposes the API Gateway (`app.apps.gateway`). The old all-in-one app is gone. |
| `app/messaging/log_consumer.py` | Uses shared consumer base; de-duplicates by `event_id` **and** content hash; stores fingerprint + correlation ID. |
| `app/messaging/metric_consumer.py` | Uses shared consumer base; stores `trace_id` on samples (alert evidence). |
| `app/messaging/publisher.py` | One connection per batch, publisher confirms, bounded retry with backoff, typed `BrokerUnavailableError`. |
| `app/messaging/trace_consumer.py` | Uses shared consumer base; tracks span count/completion, correlation ID, attributes; re-opens a trace when a late span arrives. |
| `app/models/alert.py` | + `severity`, `trace_ids`, `acknowledged_at`, `resolved_at`. |
| `app/models/diagnostic_report.py` | + `root_cause_status`, `rules_version`. |
| `app/models/ingestion_event.py` | + `correlation_id`, `raw_event` (outbox), `publish_attempts`, extra indexes. |
| `app/models/metric_sample.py` | + `trace_id`, composite index. |
| `app/models/notification_attempt.py` | Removed cross-database foreign key to `orders`. |
| `app/models/payment_attempt.py` | Removed cross-database foreign key to `orders`. |
| `app/models/processed_log.py` | + `correlation_id`, `message_fingerprint`, unique `dedup_hash`, extra indexes. |
| `app/models/trace.py` | + `correlation_id`, `span_count`, `missing_span_count`, `completion_status`, `last_span_received_at`. |
| `app/models/trace_span.py` | + `correlation_id`, `attributes`, extra indexes. |
| `app/sample_services/notification_service.py` | Own DB, scenarios (`notification_timeout`), shared instrumentation, health/ready. |
| `app/sample_services/order_service.py` | Scenario header, validates payment response, marks order paid/payment_failed, correlation-ID propagation. |
| `app/sample_services/payment_service.py` | No longer reads the order DB (gets amount/customer in the request); all failure scenarios. |
| `app/schemas/dashboard.py` | + p99, window, `partial`, `warnings`. |
| `app/schemas/dependency_graph.py` | Nodes/edges now carry request count, error rate, avg latency, observed failures. |
| `app/schemas/diagnostic.py` | Report + evidence items + warnings + list response. |
| `app/schemas/log.py` | Severity normalisation (INFO/WARNING/ERROR/CRITICAL), optional fields, unstructured messages. |
| `app/schemas/log_query.py` | + `correlation_id`, log-pattern response. |
| `app/schemas/metric.py` | Rejects NaN/inf, optional unit/labels. |
| `app/schemas/observability_query.py` | Composite trace response (`partial`, `warnings`). |
| `app/schemas/telemetry.py` | Payload is validated per event type at ingestion; UTC + service-name normalisation; correlation ID; batch models. |
| `app/schemas/trace.py` | Status normalisation, UTC, attribute sanitising (drops secret-looking keys). |
| `app/schemas/trace_query.py` | Trace list/detail/span responses with slow/failed/orphan flags. |
| `app/services/alerting.py` | Four configurable alert types, de-duplication, cooldown, auto-resolve, trace evidence. |
| `app/services/dashboard.py` | Now composes the overview from the trace + metrics services (HTTP) with partial-failure handling. |
| `app/services/dependency_graph.py` | Adds error rate, latency, failure relationships, per-service detail. |
| `app/services/metric_aggregation.py` | Time buckets, idempotent recompute, late-sample refresh, nearest-rank p50/p90/p95/p99, MySQL-independent upsert. |
| `app/services/observability_query.py` | HTTP composition helpers + error translation for the Query Service. |
| `app/services/root_cause_analysis.py` | Fetches trace/logs/metrics/alerts over HTTP, applies the rules, stores report + evidence. |
| `app/services/service_health.py` | Nearest-rank percentiles, optional time window. |
| `docker-compose.yml` | Rewritten: 16 containers (gateway, 6 services, 3 consumers, 3 sample services, `migrate`, MySQL, RabbitMQ), one DB per service, health checks, env-driven config. |
| `requirements.txt` | Added `PyJWT` (console login tokens). |

## 5. Newly added files (70)

| File | What changed |
|---|---|
| `.env.example` | All environment variables with safe placeholders. |
| `alembic.ini` | Alembic config (one migration branch per service). |
| `alembic/env.py` | Per-service Alembic environment (`ALEMBIC_SERVICE`). |
| `alembic/script.py.mako` | Migration template. |
| `alembic/versions/ingestion_0001_create_ingestion_tables.py` | Initial migration for the `ingestion` database. |
| `alembic/versions/logs_0001_create_logs_tables.py` | Initial migration for the `logs` database. |
| `alembic/versions/logs_0002_microsecond_timestamps.py` | Upgrades log timestamps to microsecond precision. |
| `alembic/versions/metrics_0001_create_metrics_tables.py` | Initial migration for the `metrics` database. |
| `alembic/versions/metrics_0002_microsecond_timestamps.py` | Upgrades metric sample timestamps to microsecond precision. |
| `alembic/versions/notifications_0001_create_notifications_tables.py` | Initial migration for the `notifications` database. |
| `alembic/versions/orders_0001_create_orders_tables.py` | Initial migration for the `orders` database. |
| `alembic/versions/payments_0001_create_payments_tables.py` | Initial migration for the `payments` database. |
| `alembic/versions/rca_0001_create_rca_tables.py` | Initial migration for the `rca` database. |
| `alembic/versions/traces_0001_create_traces_tables.py` | Initial migration for the `traces` database. |
| `alembic/versions/traces_0002_microsecond_timestamps.py` | Upgrades span/trace timestamps to microsecond precision. |
| `app/api/dependencies.py` | Dependency graph endpoints. |
| `app/api/logs.py` | Log endpoints: search, by id, patterns, logs of a trace. |
| `app/api/traces.py` | Trace endpoints: list, detail, spans, stats. |
| `app/apps/__init__.py` | Package marker. |
| `app/apps/gateway.py` | **API Gateway** service. |
| `app/apps/ingestion.py` | **Telemetry Ingestion** service app (+ outbox relay worker). |
| `app/apps/log_service.py` | **Log Processing** read API app. |
| `app/apps/metrics_service.py` | **Metrics Aggregation + Alerting** app (+ aggregation/alert worker). |
| `app/apps/query_service.py` | **Observability Query** app. |
| `app/apps/rca_service.py` | **Root-Cause Analysis** app. |
| `app/apps/trace_service.py` | **Trace Processing** read API app (+ trace completion worker). |
| `app/core/__init__.py` | Package marker. |
| `app/core/background.py` | Periodic background task runner. |
| `app/core/context.py` | Correlation-ID context + propagation headers. |
| `app/core/errors.py` | Consistent error format, no stack traces to clients. |
| `app/core/health.py` | `/health` and `/ready` endpoints. |
| `app/core/http_client.py` | Service-to-service client: timeouts, bounded retries, typed errors. |
| `app/core/logging.py` | Structured JSON logs with secret redaction. |
| `app/core/middleware.py` | Correlation-ID and request-size-limit middleware. |
| `app/core/security.py` | Internal token, API key, JWT, roles, input sanitising. |
| `app/core/stats.py` | Percentile (nearest-rank), error-rate, throughput helpers. |
| `app/core/timeutils.py` | UTC and service-name normalisation. |
| `app/db/__init__.py` | Package marker. |
| `app/db/migrate.py` | Creates the per-service databases and runs all migrations (used by the `migrate` container). |
| `app/db/registry.py` | Which tables belong to which service database. |
| `app/db/types.py` | Microsecond-precision DATETIME for span/log/metric timestamps (MySQL default drops fractions of a second). |
| `app/messaging/consumer_base.py` | Shared consumer loop: ack, retry queue, dead-letter queue, reconnect. |
| `app/models/alert_rule.py` | Runtime-configurable alert thresholds. |
| `app/sample_services/scenarios.py` | The six failure scenarios. |
| `app/schemas/alert.py` | Alert request/response schemas. |
| `app/services/ingestion.py` | Validate, store in outbox, publish; relay; statistics. |
| `app/services/log_normalization.py` | Severity, fingerprint, de-duplication hash. |
| `app/services/metric_queries.py` | Summary / per-service / latency / time-series calculations. |
| `app/services/rca_rules.py` | Deterministic diagnostic rules (pure functions). |
| `app/services/trace_analysis.py` | Trace reconstruction, self-time, request path (pure functions). |
| `app/services/trace_completion.py` | Trace completion policy. |
| `app/telemetry/__init__.py` | Package marker. |
| `app/telemetry/client.py` | Buffered HTTP telemetry sender (retries, backoff). |
| `app/telemetry/instrument.py` | One-call tracing + log + metric instrumentation. |
| `app/telemetry/otel_exporter.py` | OpenTelemetry exporter to the Ingestion Service. |
| `tests/__init__.py` | Package marker. |
| `tests/conftest.py` | Fixtures: in-memory SQLite, in-process service wiring, inline broker. |
| `tests/test_api_metrics_alerts.py` | Metrics + alert APIs, transitions, roles, rules. |
| `tests/test_api_traces_logs.py` | Trace/log/dependency APIs: filters, pagination, 404/422/400, sanitising. |
| `tests/test_consumers.py` | Duplicate delivery, out-of-order, missing span, ack/retry/dead-letter behaviour. |
| `tests/test_ingestion_api.py` | Ingestion validation, batch, duplicates, size limits, broker outage + relay, auth. |
| `tests/test_pipeline_e2e.py` | Real OpenTelemetry spans through ingestion, consumers, query and root cause. |
| `tests/test_rca_query_gateway.py` | RCA API, Query Service partial failures, Gateway auth/roles/error origin, HTTP client. |
| `tests/test_sample_services.py` | Order, Payment, Notification flow and the six failure scenarios. |
| `tests/test_security_health.py` | JWT, fail-closed secrets, readiness, no stack traces, DB failure. |
| `tests/test_unit_alerts.py` | Alert de-duplication, cooldown, auto-resolve, trace evidence, rule overrides. |
| `tests/test_unit_logs.py` | Log normalisation, fingerprints, de-duplication hash. |
| `tests/test_unit_metrics.py` | Percentiles, error rate, aggregation idempotency, missing intervals. |
| `tests/test_unit_rca.py` | Diagnostic rules: first failing span, confirmed vs probable, insufficient telemetry. |
| `tests/test_unit_trace_analysis.py` | Trace reconstruction, parent/child, durations, self-time, missing/duplicate spans. |

## 6. Untouched files (13)

`app/api/__init__.py`, `app/messaging/__init__.py`, `app/messaging/otel_rabbitmq_exporter.py`, `app/models/__init__.py`, `app/models/diagnostic_evidence.py`, `app/models/metric_aggregate.py`, `app/models/order.py`, `app/sample_services/__init__.py`, `app/schemas/__init__.py`, `app/schemas/metric_aggregation.py`, `app/schemas/metric_query.py`, `app/schemas/service_health.py`, `app/services/__init__.py`

---

## 7. API changes you must know about

* **Old paths removed:** everything under `/api/v1/observability/*` is replaced by the task's paths:
  `/api/v1/traces[/{id}[/spans|/logs]]`, `/api/v1/logs[/{id}|/patterns]`, `/api/v1/metrics/{services|summary|timeseries|latency|aggregates}`, `/api/v1/dependencies[/{service}]`, `/api/v1/diagnostics[/{id}]`, `POST /api/v1/diagnostics/analyze/{trace_id}`, `/api/v1/alerts[/{id}]`, plus `/api/v1/overview` and `/api/v1/services/health`.
* **Error format** (all services): `{"error": {"code", "message", "source", "correlation_id", "details"}}` instead of `{"detail": ...}`.
* **Auth:** everything through the gateway needs `Authorization: Bearer <jwt>` (login at `POST /api/v1/auth/login`). Telemetry needs `X-API-Key`. Roles: `viewer` (traces, metrics, dependencies, alerts), `analyst` (+ logs, diagnostics, acknowledge/resolve alerts, sample requests), `admin` (+ thresholds, manual aggregation, retry-failed).
* **Gateway vs downstream errors:** errors created by the gateway carry header `X-Error-Source: gateway` and `error.source = "api-gateway"`; downstream failures carry `X-Error-Source: downstream` (timeout gives 504, unreachable gives 503).
* Responses carry `X-Correlation-ID` (generated if you do not send one). It is propagated to every downstream call and stored on spans, logs and traces; search with `?correlation_id=`.

## 8. Design decisions you may be asked about

**Broker: RabbitMQ.** Topic exchange `telemetry.events`, routing keys `telemetry.trace|log|metric`, queues `<name>.processing`, `.retry` (5 s TTL, then back to the main queue) and `.dead-letter`.
*Guarantees:* durable queues + persistent messages + publisher confirms + manual acks give **at-least-once** delivery. The ingestion service stores each event before publishing (outbox) and a relay re-publishes after a broker outage. *Exactly-once is not claimed:* a message may be delivered twice (for example a crash after the DB write but before the ack), so every consumer is idempotent (unique `event_id`, `(trace_id, span_id)`, or content hash). *Limitations:* ordering is not guaranteed (traces tolerate out-of-order spans); retries use a fixed delay; poison messages stay in the dead-letter queue until someone inspects them; a single RabbitMQ node is a single point of failure.

**Percentile:** nearest-rank. The p-th percentile of N values is the value at rank `ceil(p/100 * N)`; it is always an observed value (no interpolation). Per-bucket percentiles are stored; wider windows are recomputed from raw samples, and percentiles are never averaged across buckets. Raw samples live in `metric_samples`, summaries in `metric_aggregates`; aggregation recomputes from raw data, so re-running it (or late samples) cannot double count.

**Alert de-duplication:** at most one open alert (`active` or `acknowledged`) per (service, type). A violation in a new bucket updates it (`last_seen_at`, `occurrence_count`, value, trace ids); the same bucket twice is ignored; recovery auto-resolves; a resolved alert cannot re-fire for `ALERT_COOLDOWN_SECONDS`; ratio alerts need `ALERT_MIN_SAMPLES` requests.

**Trace completion:** a trace stays `in_progress` until no span has arrived for `TRACE_COMPLETION_WAIT_SECONDS`, then becomes `complete` (all parents present) or `incomplete` (missing parent spans). A late span re-opens it.

**Root cause:** the *origin* is the failed span with no failed descendant and the earliest end time (errors surface bottom-up, so the gateway's 502 is a symptom and the payment failure is the origin). Status is `confirmed` only for a complete trace with an error message or a corroborating log/alert; otherwise `probable` or `inconclusive`; a healthy complete trace is `no_issue_detected`. Weights and thresholds come from the `RCA_*` and alert env variables.

## 9. What I could and could not verify

* **Verified:** all 139 tests pass; every migration applies (on SQLite); all service modules import; OpenTelemetry instrumentation runs and produces spans, logs and metrics; the end-to-end test runs real OpenTelemetry spans through exporter, ingestion, consumers, trace completion, query and root-cause analysis.
* **Not verified (no Docker, MySQL or RabbitMQ in my environment):** `docker compose up`; the migrations on real MySQL 8; real RabbitMQ delivery and the retry/dead-letter queues (tested with a fake channel); real network timeouts (simulated). Please run the stack once and report any container that fails to start.
* **Not included:** frontend (as agreed), Nginx, Kafka (RabbitMQ chosen), Postman collection. Console users come from environment variables, which is fine for development but should be replaced by a real identity store for production.

---

## 10. Fixes after the first real run

Running the stack on MySQL exposed two bugs that SQLite tests could not show:

1. **`migrate` could not connect** (it tried to open a database before creating it): fixed in `app/db/session.py`.
2. **Wrong root cause and 0 ms durations.** MySQL `DATETIME` drops fractions of a second, so all spans looked simultaneous, and OpenTelemetry's internal `... http send` spans were counted as failure origins. Fixed with microsecond columns (`app/db/types.py` + the three `*_0002_*` migrations) and by not exporting those internal spans.

**To apply on an existing install:** extract this zip over the project, then `docker compose down -v --remove-orphans` and `docker compose up --build`. (`-v` is recommended: traces stored before the fix have truncated timestamps.)
