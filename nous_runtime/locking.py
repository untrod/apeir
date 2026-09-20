"""Cross-platform advisory file locking for local runtime stores."""

from __future__ import annotations

import os
from contextlib import contextmanager
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from dataclasses import asdict, dataclass


class LockTimeoutError(TimeoutError):
    """Raised when a named Runtime lock cannot be acquired in time."""


@dataclass
class LockObservation:
    domain: str
    owner: str
    acquisition_time: float = 0.0
    wait_time: float = 0.0
    timeout: float = 0.0
    failure_reason: str = ""


class DomainLockManager:
    """Observable in-process lock domains for Runtime ownership boundaries."""

    VALID_PREFIXES = ("run:", "workspace:", "library:", "migration:")

    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}
        self._observations: dict[str, LockObservation] = {}

    @contextmanager
    def acquire(self, domain: str, *, owner: str, timeout: float = 5.0) -> Iterator[LockObservation]:
        if not domain.startswith(self.VALID_PREFIXES):
            raise ValueError(f"Unsupported lock domain: {domain}")
        bounded_timeout = max(0.0, float(timeout))
        with self._guard:
            lock = self._locks.setdefault(domain, threading.Lock())
        started = time.monotonic()
        acquired = lock.acquire(timeout=bounded_timeout)
        waited = time.monotonic() - started
        observation = LockObservation(
            domain=domain,
            owner=owner,
            acquisition_time=time.time() if acquired else 0.0,
            wait_time=waited,
            timeout=bounded_timeout,
            failure_reason="" if acquired else "timeout",
        )
        with self._guard:
            self._observations[domain] = observation
        if not acquired:
            raise LockTimeoutError(f"Timed out acquiring {domain} for {owner}")
        try:
            yield observation
        finally:
            lock.release()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._guard:
            return {
                domain: asdict(record)
                for domain, record in sorted(self._observations.items())
            }


runtime_locks = DomainLockManager()


@contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
