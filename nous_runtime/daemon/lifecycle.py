# -*- coding: utf-8 -*-
"""Daemon Lifecycle — state machine with crash recovery."""
from __future__ import annotations
import logging
from enum import Enum
from typing import Any

_log = logging.getLogger("nous.daemon.lifecycle")

class DaemonState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    DEGRADED = "degraded"
    CRASHED = "crashed"

class DaemonLifecycle:
    VALID_TRANSITIONS = {
        DaemonState.STOPPED: {DaemonState.STARTING},
        DaemonState.STARTING: {DaemonState.RUNNING, DaemonState.CRASHED},
        DaemonState.RUNNING: {DaemonState.STOPPING, DaemonState.DEGRADED, DaemonState.CRASHED},
        DaemonState.DEGRADED: {DaemonState.RUNNING, DaemonState.STOPPING, DaemonState.CRASHED},
        DaemonState.CRASHED: {DaemonState.STARTING},
        DaemonState.STOPPING: {DaemonState.STOPPED},
    }

    def __init__(self):
        self.state = DaemonState.STOPPED
        self._crash_count = 0
        self._max_crash_count = 5

    def can_transition(self, target: DaemonState) -> bool:
        return target in self.VALID_TRANSITIONS.get(self.state, set())

    def transition(self, target: DaemonState) -> bool:
        if not self.can_transition(target):
            _log.warning("Invalid transition: %s -> %s", self.state.value, target.value)
            return False
        if target == DaemonState.CRASHED:
            self._crash_count += 1
        self.state = target
        return True

    def should_auto_restart(self) -> bool:
        return self._crash_count < self._max_crash_count

    def reset_crash_count(self) -> None:
        self._crash_count = 0

    def status(self) -> dict[str, Any]:
        return {"state": self.state.value, "crash_count": self._crash_count}
