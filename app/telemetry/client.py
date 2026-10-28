"""Non-blocking telemetry sender: instrumented services -> Ingestion Service.

Events are queued in memory and flushed in batches by a background thread via
``POST /api/v1/telemetry/batch`` with bounded retries and exponential backoff.
If the ingestion service stays unreachable the batch is dropped (counted in
``dropped``) - instrumentation must never take the application down.
"""

import logging
import queue
import threading
import time

import httpx

from app.core.config import settings
from app.core.timeutils import utcnow

# Never route this module's own logs back into telemetry (feedback loop).
logger = logging.getLogger("app.telemetry.client")


class TelemetryClient:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=settings.telemetry_queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.dropped = 0

    def start(self) -> "TelemetryClient":
        if self._thread is None and settings.telemetry_enabled:
            self._thread = threading.Thread(target=self._run, name="telemetry-sender", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.flush()

    def emit(self, event_type: str, payload: dict, trace_id: str | None = None,
             correlation_id: str | None = None, event_id: str | None = None, timestamp=None) -> None:
        if not settings.telemetry_enabled:
            return
        event = {
            "event_type": event_type,
            "service_name": self.service_name,
            "timestamp": (timestamp or utcnow()).isoformat(),
            "payload": payload,
        }
        if trace_id:
            event["trace_id"] = trace_id
        if correlation_id:
            event["correlation_id"] = correlation_id
        if event_id:
            event["event_id"] = event_id
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    # ------------------------------------------------------------------
    def _drain(self, limit: int) -> list[dict]:
        batch: list[dict] = []
        while len(batch) < limit:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def flush(self) -> None:
        while True:
            batch = self._drain(settings.telemetry_batch_size)
            if not batch:
                return
            self._send(batch)

    def _run(self) -> None:
        while not self._stop.wait(settings.telemetry_flush_interval_seconds):
            try:
                self.flush()
            except Exception:  # pragma: no cover - sender must never die
                logger.exception("Telemetry flush failed")

    def _send(self, batch: list[dict]) -> None:
        url = f"{settings.ingestion_service_url.rstrip('/')}/api/v1/telemetry/batch"
        headers = {"X-API-Key": settings.ingestion_api_key}
        for attempt in range(1, 4):
            try:
                response = httpx.post(url, json={"events": batch}, headers=headers,
                                      timeout=settings.downstream_timeout_seconds)
                if response.status_code < 300:
                    self.sent += len(batch)
                    return
                if response.status_code < 500:  # definitive rejection (auth/validation)
                    logger.warning("Ingestion rejected %s events: HTTP %s", len(batch), response.status_code)
                    self.dropped += len(batch)
                    return
            except httpx.HTTPError:
                pass
            if attempt < 3:
                time.sleep(0.2 * 2 ** (attempt - 1))
        self.dropped += len(batch)
        logger.warning("Ingestion service unreachable; dropped %s telemetry events", len(batch))


_clients: dict[str, TelemetryClient] = {}


def get_telemetry_client(service_name: str) -> TelemetryClient:
    client = _clients.get(service_name)
    if client is None:
        client = _clients[service_name] = TelemetryClient(service_name).start()
    return client
