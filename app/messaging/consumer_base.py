"""Shared RabbitMQ consumer loop with acknowledgement, retry and dead-lettering.

Delivery semantics (documented limitation): RabbitMQ + manual acks gives
**at-least-once** delivery. A message can be delivered more than once (for
example if a consumer crashes after writing to the DB but before acking), so
every handler is idempotent. Exactly-once processing is NOT claimed.

Per message:
* success                         -> ack
* permanent failure (bad JSON, schema/validation error)
                                  -> publish to ``<queue>.dead-letter`` then ack
* transient failure (DB down ...) -> publish to ``<queue>.retry`` (TTL delay,
                                     then routed back to the main queue) up to
                                     MAX retries, then dead-letter
* could not retry/dead-letter     -> nack(requeue=True) so nothing is lost
"""

import json
import logging
import time
from collections.abc import Callable

import pika
from pika.exceptions import AMQPError
from pydantic import ValidationError

from app.core.config import settings
from app.messaging.publisher import EXCHANGE_NAME

logger = logging.getLogger(__name__)

PERMANENT_ERRORS = (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError)


def handle_message(channel, method, properties, body: bytes, *, name: str,
                   handler: Callable[[dict], None], queue: str,
                   max_retries: int | None = None) -> str:
    """Process one delivery. Returns the outcome (for tests/metrics)."""
    max_retries = settings.consumer_max_retries if max_retries is None else max_retries
    retry_queue, dead_letter_queue = f"{queue}.retry", f"{queue}.dead-letter"
    headers = dict(properties.headers or {}) if properties else {}
    retry_count = int(headers.get("x-retry-count", 0))
    message_id = getattr(properties, "message_id", None)

    def dead_letter(reason: str) -> str:
        try:
            channel.basic_publish(
                exchange="", routing_key=dead_letter_queue, body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2, content_type="application/json", message_id=message_id,
                    headers={**headers, "dead_letter_reason": reason[:200]},
                ),
                mandatory=True,
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.error("%s: message %s moved to dead-letter queue: %s", name, message_id, reason)
            return "dead_lettered"
        except Exception:
            logger.exception("%s: dead-letter publish failed; requeueing %s", name, message_id)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return "requeued"

    try:
        handler(json.loads(body.decode("utf-8")))
    except PERMANENT_ERRORS as exc:
        logger.warning("%s: invalid message %s: %s", name, message_id, exc)
        return dead_letter(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        logger.exception("%s: processing failed for message %s", name, message_id)
        if retry_count >= max_retries:
            return dead_letter(f"max retries exceeded: {type(exc).__name__}: {exc}")
        try:
            channel.basic_publish(
                exchange="", routing_key=retry_queue, body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2, content_type="application/json", message_id=message_id,
                    headers={**headers, "x-retry-count": retry_count + 1},
                ),
                mandatory=True,
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.warning("%s: retry %s/%s scheduled for %s", name, retry_count + 1, max_retries, message_id)
            return "retry_scheduled"
        except Exception:
            logger.exception("%s: retry publish failed; requeueing %s", name, message_id)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return "requeued"

    channel.basic_ack(delivery_tag=method.delivery_tag)
    return "acked"


def _declare_topology(channel, queue: str, routing_key: str) -> None:
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)
    channel.queue_declare(queue=queue, durable=True)
    channel.queue_bind(exchange=EXCHANGE_NAME, queue=queue, routing_key=routing_key)
    channel.queue_declare(queue=f"{queue}.dead-letter", durable=True)
    channel.queue_declare(
        queue=f"{queue}.retry", durable=True,
        arguments={
            "x-message-ttl": settings.consumer_retry_delay_ms,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": routing_key,
        },
    )


def run_consumer(*, name: str, queue: str, routing_key: str, handler: Callable[[dict], None]) -> None:
    """Consume forever; reconnect with backoff if the broker goes away."""
    backoff = 2.0
    while True:
        connection = None
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=settings.rabbitmq_host, port=settings.rabbitmq_port,
                credentials=pika.PlainCredentials(settings.rabbitmq_default_user, settings.rabbitmq_default_pass),
                heartbeat=60, blocked_connection_timeout=30,
            ))
            channel = connection.channel()
            _declare_topology(channel, queue, routing_key)
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(
                queue=queue, auto_ack=False,
                on_message_callback=lambda ch, m, p, b: handle_message(
                    ch, m, p, b, name=name, handler=handler, queue=queue),
            )
            logger.info("%s started (queue=%s, max_retries=%s, retry_delay=%sms)",
                        name, queue, settings.consumer_max_retries, settings.consumer_retry_delay_ms)
            backoff = 2.0
            channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Stopping %s", name)
            return
        except (AMQPError, OSError) as exc:
            logger.warning("%s lost broker connection (%s); reconnecting in %.0fs",
                           name, type(exc).__name__, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        finally:
            if connection is not None and connection.is_open:
                try:
                    connection.close()
                except Exception:  # pragma: no cover
                    pass
