from __future__ import annotations

import threading
from typing import Callable


class PushWorker:
    def __init__(self, dispatch_once: Callable[[], None], interval_seconds: float = 0.5) -> None:
        self._dispatch_once = dispatch_once
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def interval_seconds(self) -> float:
        return self._interval_seconds

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self, timeout_seconds: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout_seconds)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._dispatch_once()
            self._stop_event.wait(self._interval_seconds)
