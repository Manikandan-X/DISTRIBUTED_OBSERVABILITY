
import json
import logging
from datetime import datetime, timezone

import pika
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from app.core.config import settings

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "telemetry.events"
ROUTING_KEY = "telemetry.trace"


def timestamp_to_datetime(timestamp_ns: int) -> datetime:
    """Convert OpenTelemetry nanoseconds to a UTC datetime."""
    return datetime.fromtimestamp(
        timestamp_ns / 1_000_000_000,
        tz=timezone.utc,
    ).replace(tzinfo=None)


class RabbitMQSpanExporter(SpanExporter):
    """Export completed OpenTelemetry spans to RabbitMQ."""

    def export(self, spans: tuple[ReadableSpan, ...]) -> SpanExportResult:
        if not spans:
            return SpanExportResult.SUCCESS

        connection = None

        try:
            credentials = pika.PlainCredentials(
                settings.rabbitmq_default_user,
                settings.rabbitmq_default_pass,
            )

            parameters = pika.ConnectionParameters(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                credentials=credentials,
                heartbeat=30,
                blocked_connection_timeout=10,
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.exchange_declare(
                exchange=EXCHANGE_NAME,
                exchange_type="topic",
                durable=True,
            )

            channel.confirm_delivery()

            for span in spans:
                context = span.context

                if context is None or not context.is_valid:
                    logger.warning("Skipping span with invalid context")
                    continue

                trace_id = format(context.trace_id, "032x")
                span_id = format(context.span_id, "016x")

                parent_span_id = None
                if span.parent is not None and span.parent.is_valid:
                    parent_span_id = format(
                        span.parent.span_id,
                        "016x",
                    )

                resource_attributes = span.resource.attributes
                service_name = resource_attributes.get(
                    "service.name",
                    "unknown-service",
                )

                status = (
                    "error"
                    if span.status.status_code == StatusCode.ERROR
                    else "ok"
                )

                error_message = None
                for event in span.events:
                    if event.name == "exception":
                        error_message = event.attributes.get(
                            "exception.message"
                        )
                        if error_message:
                            break

                start_time = timestamp_to_datetime(span.start_time)
                end_time = timestamp_to_datetime(span.end_time)

                event_data = {
                    "event_id": f"otel-{trace_id}-{span_id}",
                    "event_type": "trace",
                    "service_name": service_name,
                    "trace_id": trace_id,
                    "timestamp": end_time.isoformat(),
                    "payload": {
                        "span_id": span_id,
                        "parent_span_id": parent_span_id,
                        "operation_name": span.name,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "status": status,
                        "error_message": error_message,
                    },
                }

                channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key=ROUTING_KEY,
                    body=json.dumps(event_data),
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                        message_id=event_data["event_id"],
                    ),
                    mandatory=True,
                )

            logger.info(
                "Exported %s OpenTelemetry spans to RabbitMQ",
                len(spans),
            )
            return SpanExportResult.SUCCESS

        except Exception:
            logger.exception("Failed to export spans to RabbitMQ")
            return SpanExportResult.FAILURE

        finally:
            if connection is not None and connection.is_open:
                connection.close()

    def shutdown(self) -> None:
        """Release exporter resources."""
        logger.info("RabbitMQ span exporter shut down")
