# -*- coding: utf-8 -*-
"""Process Supervisor — health monitoring and auto-recovery."""
from __future__ import annotations
import logging
import threading
import time
from typing import Callable

_log = logging.getLogger("nous.daemon.supervisor")

class ProcessSupervisor:
    def __init__(self, check_fn: Callable[[], bool] | None = None, check_interval_sec: float = 15.0):
        self._check_fn = check_fn or (lambda: True)
        self._interval = check_interval_sec
        self._running = False
        self._thread: threading.Thread | None = None
        self.on_unhealthy: Callable[[], None] | None = None
        self._unhealthy_count = 0
        self._max_unhealthy = 3

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running:
            try:
                healthy = self._check_fn()
                if not healthy:
                    self._unhealthy_count += 1
                    if self._unhealthy_count >= self._max_unhealthy and self.on_unhealthy:
                        self.on_unhealthy()
                        self._unhealthy_count = 0
                else:
                    self._unhealthy_count = 0
            except Exception:
                pass
            time.sleep(self._interval)

    def check_now(self) -> bool:
        try:
            return self._check_fn()
        except Exception:
            return False
