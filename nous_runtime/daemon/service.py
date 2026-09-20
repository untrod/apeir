# -*- coding: utf-8 -*-
"""DaemonService — systemd/launchd/windows-service integration."""
from __future__ import annotations
import logging
import platform
import signal
import sys
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.daemon")

class DaemonService:
    """Manages Nous Runtime as a background daemon."""
    def __init__(self, workspace: str = "", host: str = "127.0.0.1", port: int = 9770):
        self._workspace = workspace or str(Path.home() / ".nous")
        self._host = host
        self._port = port
        self._running = False
        self._started_at = ""

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        try:
            _log.info("Starting Nous daemon on %s:%d", self._host, self._port)
            self._running = True
            from datetime import datetime, timezone
            self._started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            Path(self._workspace).mkdir(parents=True, exist_ok=True)
            self._restore_context()
            _log.info("Nous daemon started")
            return True
        except Exception as exc:
            _log.error("Failed to start daemon: %s", exc)
            self._running = False
            return False

    def stop(self) -> bool:
        _log.info("Stopping Nous daemon...")
        self._running = False
        return True

    def wait(self) -> None:
        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        while self._running:
            time.sleep(1)

    def status(self) -> dict[str, Any]:
        return {"running": self._running, "host": self._host, "port": self._port,
                "workspace": self._workspace, "started_at": self._started_at,
                "platform": platform.platform(), "python": sys.version}

    def _restore_context(self) -> None:
        try:
            from nous_runtime.context.snapshot import restore_snapshot
            result = restore_snapshot(workspace=self._workspace)
            if result.success:
                _log.info("Context restored: %d items", result.restored_items)
        except Exception as exc:
            _log.warning("Context restore skipped: %s", exc)
