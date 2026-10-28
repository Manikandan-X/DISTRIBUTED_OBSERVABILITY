"""Which tables belong to which service-owned database.

Every service owns one schema. A service must never query another service's
tables; it calls the owning service's HTTP API instead.
"""

SERVICE_TABLES: dict[str, list[str]] = {
    "ingestion": ["ingestion_events"],
    "traces": ["traces", "trace_spans"],
    "logs": ["processed_logs"],
    "metrics": ["metric_samples", "metric_aggregates", "alerts", "alert_rules"],
    "rca": ["diagnostic_reports", "diagnostic_evidence"],
    "orders": ["orders"],
    "payments": ["payment_attempts"],
    "notifications": ["notification_attempts"],
}

# Database (schema) name used by each service. Override with env DB_<KEY>.
DEFAULT_DATABASES: dict[str, str] = {
    "ingestion": "obs_ingestion",
    "traces": "obs_traces",
    "logs": "obs_logs",
    "metrics": "obs_metrics",
    "rca": "obs_rca",
    "orders": "obs_orders",
    "payments": "obs_payments",
    "notifications": "obs_notifications",
}
