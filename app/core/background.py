"""Tiny periodic background task runner (daemon thread)."""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class PeriodicTask:
    def __init__(self, name: str, interval_seconds: float, func: Callable[[], None]):
        self.name = name
        self.interval = interval_seconds
        self.func = func
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.func()
            except Exception:
                logger.exception("Background task '%s' failed; will retry", self.name)

    def start(self) -> "PeriodicTask":
        self._thread.start()
        logger.info("Started background task '%s' every %ss", self.name, self.interval)
        return self

    def stop(self) -> None:
        self._stop.set()
