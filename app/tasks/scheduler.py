from __future__ import annotations

import logging
import threading
import time
from typing import Callable

LOGGER = logging.getLogger(__name__)


class RepeatedTask:
    """Tiny scheduler that runs a callable every N seconds."""

    def __init__(self, interval: int, target: Callable[[], None]):
        self.interval = interval
        self.target = target
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.target()
            except Exception as exc:  # noqa: BLE001 - we want to log everything
                LOGGER.error('Scheduled task failed: %s', exc)
            self._stop_event.wait(self.interval)


def start_offline_sync(service, interval_seconds: int = 300) -> RepeatedTask:
    """Launch the offline buffer sync task and return the handler."""

    task = RepeatedTask(interval_seconds, service.sync_offline_buffer)
    task.start()
    return task
