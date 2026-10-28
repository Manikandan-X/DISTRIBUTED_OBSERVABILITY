import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.telemetry.client import get_telemetry_client
from app.telemetry.otel_exporter import IngestionSpanExporter

logger = logging.getLogger(__name__)


def configure_tracing(service_name: str) -> None:
    """Configure OpenTelemetry tracing for one service.

    Spans are exported to the Telemetry Ingestion Service over HTTP (not
    straight to RabbitMQ), so every producer goes through validation.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(IngestionSpanExporter(get_telemetry_client(service_name)), schedule_delay_millis=1000)
    )
    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry configured for service: %s", service_name)
