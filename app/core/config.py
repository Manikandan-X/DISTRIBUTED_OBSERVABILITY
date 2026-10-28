from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Distributed Observability Platform"
    app_version: str = "1.0.0"
    service_name: str = "observability-service"

    # --- Database (each service points at its OWN database) -------------
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_root_password: str = ""
    mysql_database: str = "observability_db"
    # Full SQLAlchemy URL override (used by the test-suite with SQLite).
    database_url: str | None = None

    # --- Broker ---------------------------------------------------------
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_default_user: str = ""
    rabbitmq_default_pass: str = ""
    broker_publish_attempts: int = 3
    broker_publish_backoff_seconds: float = 0.5
    consumer_max_retries: int = 3
    consumer_retry_delay_ms: int = 5000

    # --- Security -------------------------------------------------------
    internal_api_token: str = ""          # service-to-service shared secret
    ingestion_api_keys: str = ""          # comma-separated telemetry API keys
    jwt_secret: str = ""
    jwt_ttl_minutes: int = 60
    console_admin_user: str = "admin"
    console_admin_password: str = ""
    console_analyst_user: str = "analyst"
    console_analyst_password: str = ""
    console_viewer_user: str = "viewer"
    console_viewer_password: str = ""
    max_request_bytes: int = 1_048_576    # 1 MiB request-body cap
    max_batch_events: int = 500

    # --- Service discovery (never hard-code URLs) -----------------------
    ingestion_service_url: str = "http://ingestion-service:8000"
    trace_service_url: str = "http://trace-service:8000"
    log_service_url: str = "http://log-service:8000"
    metrics_service_url: str = "http://metrics-service:8000"
    rca_service_url: str = "http://rca-service:8000"
    query_service_url: str = "http://query-service:8000"
    order_service_url: str = "http://order-service:8000"
    payment_service_url: str = "http://payment-service:8000"
    notification_service_url: str = "http://notification-service:8000"
    ingestion_api_key: str = ""           # key this service uses to SEND telemetry

    # --- Timeouts / retries ----------------------------------------------
    downstream_timeout_seconds: float = 5.0
    downstream_max_attempts: int = 3
    downstream_backoff_seconds: float = 0.2
    gateway_timeout_seconds: float = 8.0

    # --- Telemetry emission (instrumented services) ----------------------
    telemetry_enabled: bool = True
    telemetry_flush_interval_seconds: float = 1.0
    telemetry_batch_size: int = 100
    telemetry_queue_size: int = 10000

    # --- Trace processing ---------------------------------------------------
    trace_completion_wait_seconds: int = 30
    slow_span_threshold_ms: float = 500.0
    slow_trace_threshold_ms: float = 1000.0
    background_workers_enabled: bool = True

    # --- Metrics / alerting -------------------------------------------------
    metric_bucket_seconds: int = 60
    aggregation_interval_seconds: int = 30
    aggregation_lookback_buckets: int = 5
    alert_min_samples: int = 5
    alert_error_rate_percent: float = 20.0
    alert_avg_latency_ms: float = 500.0
    alert_p95_latency_ms: float = 1000.0
    alert_request_volume: float = 1000.0
    alert_cooldown_seconds: int = 300

    # --- Root-cause analysis rules (deterministic, configurable) ----------
    rca_failed_origin_weight: float = 50.0
    rca_failed_symptom_weight: float = 15.0
    rca_error_log_weight: float = 3.0
    rca_latency_share_weight: float = 30.0
    rca_elevated_error_rate_weight: float = 15.0
    rca_elevated_latency_weight: float = 10.0
    rca_active_alert_weight: float = 10.0
    rca_bottleneck_min_share: float = 0.5
    rca_metric_window_minutes: int = 60

    # --- Sample application -------------------------------------------------
    default_failure_scenario: str = "normal"
    allow_scenario_header: bool = True
    slow_payment_seconds: float = 2.0
    notification_timeout_seconds: float = 6.0
    sample_call_timeout_seconds: float = 3.0
    intermittent_failure_rate: float = 0.5

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
