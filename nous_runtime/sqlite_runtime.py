"""Observable SQLite Alpha runtime without replacing the authoritative backend."""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


class SQLiteRuntime:
    """Short-lived SQLite connections with bounded retry and telemetry."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._guard = threading.RLock()
        self._transaction_ms: deque[float] = deque(maxlen=2_048)
        self._lock_wait_ms: deque[float] = deque(maxlen=2_048)
        self._active_writers = 0
        self._busy_retries = 0
        self._checkpoint_ms = 0.0
        self._last_backup_at = 0.0

    @contextmanager
    def connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """Open one bounded, always-closed transaction."""
        started = time.perf_counter()
        if not readonly:
            with self._guard:
                self._active_writers += 1
        try:
            target = f"file:{self.path}?mode=ro" if readonly else str(self.path)
            connection = sqlite3.connect(
                target, uri=readonly, timeout=self.busy_timeout_ms / 1_000
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            connection.execute("PRAGMA foreign_keys=ON")
            if not readonly:
                connection.execute("PRAGMA journal_mode=WAL")
            lock_wait_ms = (time.perf_counter() - started) * 1_000
            try:
                yield connection
                if not readonly:
                    connection.commit()
            except Exception:
                if not readonly:
                    connection.rollback()
                raise
            finally:
                connection.close()
                with self._guard:
                    self._transaction_ms.append(
                        (time.perf_counter() - started) * 1_000
                    )
                    self._lock_wait_ms.append(lock_wait_ms)
        finally:
            if not readonly:
                with self._guard:
                    self._active_writers -= 1

    def execute(
        self, sql: str, params: Sequence[Any] = (), *, retries: int = 2
    ) -> int:
        """Execute one short write transaction with bounded busy retry."""
        for attempt in range(max(0, retries) + 1):
            try:
                with self.connect() as connection:
                    return connection.execute(sql, tuple(params)).rowcount
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt >= retries:
                    raise
                with self._guard:
                    self._busy_retries += 1
                time.sleep(min(0.01 * (2 ** attempt), 0.05))
        raise RuntimeError("unreachable SQLite retry state")

    def batch(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        """Execute a justified batch in one transaction."""
        with self.connect() as connection:
            return connection.executemany(
                sql, [tuple(row) for row in rows]
            ).rowcount

    def explain_query_plan(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        if not sql.lstrip().lower().startswith(("select", "with")):
            raise ValueError("Query-plan inspection accepts read queries only")
        with self.connect(readonly=True) as connection:
            rows = connection.execute(
                f"EXPLAIN QUERY PLAN {sql}", tuple(params)
            ).fetchall()
        return [dict(row) for row in rows]

    def checkpoint(self, mode: str = "PASSIVE") -> dict[str, Any]:
        normalized = mode.upper()
        if normalized not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"Unsupported checkpoint mode: {mode}")
        started = time.perf_counter()
        with self.connect() as connection:
            row = connection.execute(
                f"PRAGMA wal_checkpoint({normalized})"
            ).fetchone()
        duration_ms = (time.perf_counter() - started) * 1_000
        with self._guard:
            self._checkpoint_ms = duration_ms
        return {
            "busy": int(row[0]),
            "log_frames": int(row[1]),
            "checkpointed_frames": int(row[2]),
            "duration_ms": duration_ms,
        }

    def record_backup(self) -> None:
        with self._guard:
            self._last_backup_at = time.time()

    def metrics(self) -> dict[str, Any]:
        with self._guard:
            transactions = list(self._transaction_ms)
            waits = list(self._lock_wait_ms)
            active = self._active_writers
            retries = self._busy_retries
            checkpoint_ms = self._checkpoint_ms
            backup_at = self._last_backup_at
        integrity = "missing"
        if self.path.is_file():
            try:
                connection = sqlite3.connect(
                    f"file:{self.path}?mode=ro", uri=True, timeout=1
                )
                try:
                    integrity = str(
                        connection.execute("PRAGMA quick_check").fetchone()[0]
                    )
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                integrity = f"error:{type(exc).__name__}"
        wal = Path(f"{self.path}-wal")
        return {
            "database_size": self.path.stat().st_size if self.path.is_file() else 0,
            "wal_size": wal.stat().st_size if wal.is_file() else 0,
            "write_queue_depth": max(active - 1, 0),
            "transaction_p50_ms": _percentile(transactions, 0.50),
            "transaction_p95_ms": _percentile(transactions, 0.95),
            "transaction_p99_ms": _percentile(transactions, 0.99),
            "lock_wait_ms": _percentile(waits, 0.95),
            "busy_retries": retries,
            "checkpoint_duration_ms": checkpoint_ms,
            "integrity_status": integrity,
            "last_backup_age_seconds": (
                max(time.time() - backup_at, 0.0) if backup_at else None
            ),
        }


def _percentile(samples: list[float], quantile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(
        max(math.ceil(len(ordered) * quantile) - 1, 0),
        len(ordered) - 1,
    )
    return round(ordered[index], 3)
