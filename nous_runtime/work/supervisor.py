"""Process-level host for durable Work execution.

The supervisor owns only ephemeral worker handles. WorkHarness checkpoints and the
canonical EventStream remain the sole source of lifecycle truth.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping

from nous_runtime.events import RunState
from nous_runtime.work.components import (
    WorkExecutionComponents,
    build_work_components,
)
from nous_runtime.work.models import WorkSnapshot
from nous_runtime.work.runtime import WorkHarness


ComponentFactory = Callable[[Path, WorkSnapshot], WorkExecutionComponents]


class WorkAlreadyRunning(RuntimeError):
    """Raised when a second worker tries to own the same durable Work run."""


class WorkSupervisor:
    """Keep Work running independently of any individual UI request."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        component_factory: ComponentFactory = build_work_components,
        max_workers: int = 4,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._component_factory = component_factory
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 32)),
            thread_name_prefix="apeir-work",
        )
        self._futures: dict[str, Future[WorkSnapshot]] = {}
        self._lock = threading.RLock()
        self._closed = False

    def start(
        self,
        objective: str,
        *,
        constraints: Mapping[str, object] | None = None,
        completion_criteria: tuple[str, ...] | list[str] = (),
        conversation_id: str = "",
        owner_id: str = "local",
        preferred_model: str = "",
        read_only: bool = False,
        max_iterations: int = 32,
    ) -> WorkSnapshot:
        harness = WorkHarness(self.root)
        snapshot = harness.create(
            objective,
            constraints=constraints,
            completion_criteria=completion_criteria,
            conversation_id=conversation_id,
            owner_id=owner_id,
            execution_options={
                "preferred_model": str(preferred_model or ""),
                "read_only": bool(read_only),
                "max_iterations": self._bounded_iterations(max_iterations),
            },
        )
        self._submit(snapshot.run_id, recovering=False)
        return harness.require(snapshot.run_id)

    def resume(self, run_id: str) -> WorkSnapshot:
        snapshot = WorkHarness(self.root).require(run_id)
        if snapshot.terminal:
            return snapshot
        self._submit(run_id, recovering=True)
        return WorkHarness(self.root).require(run_id)

    def recover(self, run_id: str) -> WorkSnapshot:
        """Resume through WorkHarness re-evaluation, never by replaying a call."""
        return self.resume(run_id)

    def pause(self, run_id: str, *, reason: str = "") -> WorkSnapshot:
        return WorkHarness(self.root).pause(run_id, reason=reason)

    def steer(
        self,
        run_id: str,
        instruction: str,
        *,
        constraints: Mapping[str, object] | None = None,
    ) -> WorkSnapshot:
        return WorkHarness(self.root).steer(
            run_id,
            instruction,
            constraints=constraints,
        )

    def cancel(self, run_id: str, *, reason: str = "") -> WorkSnapshot:
        snapshot = WorkHarness(self.root).cancel(run_id, reason=reason)
        with self._lock:
            future = self._futures.get(run_id)
            if future is not None:
                future.cancel()
        return snapshot

    def attach(self, run_id: str) -> dict[str, object]:
        """Return durable facts plus the current process-local worker status."""
        report = WorkHarness(self.root).inspect(run_id)
        report["supervisor"] = self._worker_projection(run_id)
        return report

    def detach(self, run_id: str) -> dict[str, object]:
        """Detach a client without changing or stopping the Work lifecycle."""
        WorkHarness(self.root).require(run_id)
        return self._worker_projection(run_id)

    def inspect(self, run_id: str) -> dict[str, object]:
        return self.attach(run_id)

    def list(self) -> list[dict[str, object]]:
        harness = WorkHarness(self.root)
        return [
            {
                "work": snapshot.to_dict(),
                "supervisor": self._worker_projection(snapshot.run_id),
            }
            for snapshot in harness.list()
        ]

    def recovery_candidates(self) -> list[WorkSnapshot]:
        return [
            snapshot
            for snapshot in WorkHarness(self.root).list()
            if not snapshot.terminal and not self.is_active(snapshot.run_id)
        ]

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
            return future is not None and not future.done()

    def wait(self, run_id: str, timeout: float | None = None) -> WorkSnapshot:
        with self._lock:
            future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        return WorkHarness(self.root).require(run_id)

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _submit(self, run_id: str, *, recovering: bool) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("work supervisor is closed")
            current = self._futures.get(run_id)
            if current is not None and not current.done():
                raise WorkAlreadyRunning(run_id)
            future = self._executor.submit(self._execute, run_id, recovering)
            self._futures[run_id] = future

    def _execute(self, run_id: str, recovering: bool) -> WorkSnapshot:
        harness = WorkHarness(self.root)
        try:
            snapshot = harness.require(run_id)
            components = self._component_factory(self.root, snapshot)
            maximum = self._bounded_iterations(
                snapshot.execution_options.get("max_iterations", 32)
            )
            if recovering:
                return harness.resume(
                    run_id,
                    deliberator=components.deliberator,
                    tools=components.tools,
                    verifier=components.verifier,
                    max_iterations=maximum,
                )
            return harness.run(
                run_id,
                deliberator=components.deliberator,
                tools=components.tools,
                verifier=components.verifier,
                max_iterations=maximum,
            )
        except Exception as exc:
            snapshot = harness.require(run_id)
            if snapshot.terminal or snapshot.state in {
                RunState.PAUSED,
                RunState.WAITING_USER,
                RunState.WAITING_FOR_APPROVAL,
            }:
                return snapshot
            return harness.fail(run_id, reason=str(exc))

    def _worker_projection(self, run_id: str) -> dict[str, object]:
        with self._lock:
            future = self._futures.get(run_id)
            active = future is not None and not future.done()
            done = future is not None and future.done()
        return {
            "run_id": run_id,
            "active": active,
            "worker_known": future is not None,
            "worker_done": done,
            "authority": "WorkHarness checkpoint + EventStream",
        }

    @staticmethod
    def _bounded_iterations(value: object) -> int:
        return max(1, min(int(value), 1_000))


_SUPERVISORS: dict[str, WorkSupervisor] = {}
_SUPERVISORS_LOCK = threading.Lock()


def get_work_supervisor(root: str | Path = ".") -> WorkSupervisor:
    """Return the process host for one workspace without creating new state."""
    key = str(Path(root).resolve())
    with _SUPERVISORS_LOCK:
        supervisor = _SUPERVISORS.get(key)
        if supervisor is None:
            supervisor = WorkSupervisor(key)
            _SUPERVISORS[key] = supervisor
        return supervisor


__all__ = [
    "ComponentFactory",
    "WorkAlreadyRunning",
    "WorkSupervisor",
    "get_work_supervisor",
]
