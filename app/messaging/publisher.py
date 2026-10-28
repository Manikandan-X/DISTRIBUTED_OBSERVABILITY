import json
import logging
import time

import pika
from pika.exceptions import AMQPError

from app.core.config import settings

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "telemetry.events"

ROUTING_KEYS = {
    "trace": "telemetry.trace",
    "log": "telemetry.log",
    "metric": "telemetry.metric",
}

QUEUE_BINDINGS = {
    "trace.processing": "telemetry.trace",
    "log.processing": "telemetry.log",
    "metric.processing": "telemetry.metric",
}


class BrokerUnavailableError(RuntimeError):
    """The broker could not accept the message(s) after bounded retries."""


def _connection_parameters() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        credentials=pika.PlainCredentials(
            settings.rabbitmq_default_user,
            settings.rabbitmq_default_pass,
        ),
        heartbeat=30,
        blocked_connection_timeout=10,
        socket_timeout=5,
        connection_attempts=1,
    )


def _publish_once(events: list[dict]) -> list[bool]:
    """Publish events over ONE connection. Returns per-event success flags."""
    connection = None
    results = [False] * len(events)
    try:
        connection = pika.BlockingConnection(_connection_parameters())
        channel = connection.channel()
        channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)
        for queue_name, routing_key in QUEUE_BINDINGS.items():
            channel.queue_declare(queue=queue_name, durable=True)
            channel.queue_bind(queue=queue_name, exchange=EXCHANGE_NAME, routing_key=routing_key)
        channel.confirm_delivery()  # publisher confirms: broker accepted the message

        for index, event in enumerate(events):
            routing_key = ROUTING_KEYS.get(event["event_type"])
            if routing_key is None:
                raise ValueError(f"Unsupported telemetry type: {event['event_type']}")
            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=routing_key,
                body=json.dumps(event, default=str),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # persistent
                    content_type="application/json",
                    message_id=event["event_id"],
                ),
                mandatory=True,
            )
            results[index] = True
    except (AMQPError, OSError) as exc:
        logger.warning("Broker publish interrupted: %s", type(exc).__name__)
        raise BrokerUnavailableError("Failed to publish telemetry to RabbitMQ") from exc
    finally:
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except Exception:  # pragma: no cover - best effort
                pass
    return results


def publish_batch(events: list[dict]) -> None:
    """Publish with bounded retries and exponential backoff.

    Raises BrokerUnavailableError when every attempt failed. Because the
    ingestion service keeps the event in its outbox (ingestion_events), a
    failure here does not lose data: the relay re-publishes later. Delivery
    is therefore *at-least-once*; consumers de-duplicate.
    """
    attempts = max(1, settings.broker_publish_attempts)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _publish_once(events)
            return
        except BrokerUnavailableError as exc:
            last = exc
            if attempt < attempts:
                time.sleep(settings.broker_publish_backoff_seconds * (2 ** (attempt - 1)))
    raise BrokerUnavailableError("Failed to publish telemetry to RabbitMQ") from last


def publish_telemetry(event: dict) -> None:
    """Publish a single event (kept for backwards compatibility)."""
    publish_batch([event])
