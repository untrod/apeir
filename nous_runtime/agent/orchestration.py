"""Bounded multi-Agent coordination with isolated workspaces."""

from __future__ import annotations

from contextlib import contextmanager

import json
import shutil
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AgentWorkItem:
    work_id: str
    objective: str
    agent_id: str
    allowed_files: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentWorkerResult:
    work_id: str
    agent_id: str
    status: str
    changed_files: tuple[str, ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()
    summary: str = ""
    error: str = ""


@dataclass
class MultiAgentRun:
    work_items: tuple[AgentWorkItem, ...]
    run_id: str = field(default_factory=lambda: f"mar_{uuid.uuid4().hex}")
    state: str = "pending"
    results: dict[str, AgentWorkerResult] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    integration: dict[str, Any] = field(default_factory=dict)
    error: str = ""


WorkerExecutor = Callable[[AgentWorkItem, Path], AgentWorkerResult]
Reviewer = Callable[[tuple[AgentWorkerResult, ...]], dict[str, Any]]


class MultiAgentCoordinator:
    def __init__(self, root: str | Path, executor: WorkerExecutor, reviewer: Reviewer, *, max_workers: int = 3):
        self.root = Path(root).resolve()
        self.executor = executor
        self.reviewer = reviewer
        self.max_workers = max(1, min(max_workers, 8))
        self.db_path = self.root / ".nous" / "multi_agent.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS multi_agent_runs (run_id TEXT PRIMARY KEY, run_json TEXT NOT NULL)")

    def start(self, work_items: tuple[AgentWorkItem, ...], *, run_id: str = "") -> MultiAgentRun:
        self._validate(work_items)
        run = MultiAgentRun(work_items, **({"run_id": run_id} if run_id else {}))
        self._save(run)
        return self._execute(run)

    def resume(self, run_id: str) -> MultiAgentRun:
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.state in {"completed", "review_rejected", "conflict"}:
            return run
        return self._execute(run)

    def get(self, run_id: str) -> MultiAgentRun | None:
        with self._db() as connection:
            row = connection.execute("SELECT run_json FROM multi_agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_from_dict(json.loads(row[0])) if row else None

    def _execute(self, run: MultiAgentRun) -> MultiAgentRun:
        run.state = "running"
        self._save(run)
        completed = {work_id for work_id, result in run.results.items() if result.status == "completed"}
        run.results = {work_id: result for work_id, result in run.results.items() if result.status == "completed"}
        while len(completed) < len(run.work_items):
            ready = [item for item in run.work_items if item.work_id not in completed and set(item.depends_on).issubset(completed)]
            if not ready:
                run.state = "failed"
                run.error = "no runnable work items"
                self._save(run)
                return run
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(ready))) as pool:
                futures = {pool.submit(self._execute_worker, run.run_id, item): item for item in ready}
                for future, item in futures.items():
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = AgentWorkerResult(item.work_id, item.agent_id, "failed", error=str(exc))
                    run.results[item.work_id] = result
                    completed.add(item.work_id)
                    self._save(run)
                    if result.status != "completed":
                        run.state = "partial_failure"
                        run.error = result.error or f"worker failed: {item.work_id}"
                        self._save(run)
                        return run
        ordered = tuple(run.results[item.work_id] for item in run.work_items)
        run.review = dict(self.reviewer(ordered) or {})
        if not run.review.get("approved", False):
            run.state = "review_rejected"
            run.error = str(run.review.get("reason") or "review rejected")
            self._save(run)
            return run
        conflicts = self._conflicts(ordered)
        if conflicts:
            run.state = "conflict"
            run.integration = {"status": "blocked", "conflicts": conflicts}
            run.error = "worker outputs overlap"
            self._save(run)
            return run
        run.integration = {"status": "proposed", "changed_files": sorted({path for result in ordered for path in result.changed_files}), "artifacts": [artifact for result in ordered for artifact in result.artifacts]}
        run.state = "completed"
        self._save(run)
        return run

    def _execute_worker(self, run_id: str, item: AgentWorkItem) -> AgentWorkerResult:
        workspace = self.root / ".nous" / "multi_agent" / run_id / item.work_id
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        for path in self.root.iterdir():
            if path.name in {".git", ".nous"}:
                continue
            target = workspace / path.name
            if path.is_dir():
                shutil.copytree(path, target, ignore=shutil.ignore_patterns(".git", ".nous", "__pycache__", ".venv", "node_modules"))
            elif path.is_file():
                shutil.copy2(path, target)
        result = self.executor(item, workspace)
        denied = set(result.changed_files) - set(item.allowed_files)
        if denied:
            return AgentWorkerResult(item.work_id, item.agent_id, "failed", result.changed_files, result.artifacts, result.summary, "worker changed files outside declared scope: " + ", ".join(sorted(denied)))
        return result

    @staticmethod
    def _conflicts(results: tuple[AgentWorkerResult, ...]) -> list[str]:
        owners: dict[str, str] = {}
        conflicts: set[str] = set()
        for result in results:
            for path in result.changed_files:
                if path in owners and owners[path] != result.work_id:
                    conflicts.add(path)
                owners[path] = result.work_id
        return sorted(conflicts)

    @staticmethod
    def _validate(items: tuple[AgentWorkItem, ...]) -> None:
        ids = [item.work_id for item in items]
        if not items or len(ids) != len(set(ids)):
            raise ValueError("work items must be non-empty and unique")
        known = set(ids)
        for item in items:
            if not item.agent_id or not item.objective:
                raise ValueError("agent_id and objective are required")
            if set(item.depends_on) - known:
                raise ValueError("unknown work dependency")
            if item.work_id in item.depends_on:
                raise ValueError("self dependency")
        edges = {item.work_id: item.depends_on for item in items}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(work_id: str) -> None:
            if work_id in visiting:
                raise ValueError("work dependency cycle")
            if work_id in visited:
                return
            visiting.add(work_id)
            for dependency in edges[work_id]:
                visit(dependency)
            visiting.remove(work_id)
            visited.add(work_id)

        for work_id in ids:
            visit(work_id)

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _save(self, run: MultiAgentRun) -> None:
        with self._db() as connection:
            connection.execute("INSERT OR REPLACE INTO multi_agent_runs VALUES (?, ?)", (run.run_id, json.dumps(self._run_dict(run), sort_keys=True)))

    @staticmethod
    def _run_dict(run: MultiAgentRun) -> dict[str, Any]:
        return {"run_id": run.run_id, "state": run.state, "error": run.error, "work_items": [dict(item.__dict__) for item in run.work_items], "results": {key: dict(value.__dict__) for key, value in run.results.items()}, "review": run.review, "integration": run.integration}

    @staticmethod
    def _run_from_dict(data: dict[str, Any]) -> MultiAgentRun:
        items = tuple(AgentWorkItem(str(item["work_id"]), str(item["objective"]), str(item["agent_id"]), tuple(item.get("allowed_files") or ()), tuple(item.get("depends_on") or ())) for item in data.get("work_items") or ())
        results = {key: AgentWorkerResult(str(value["work_id"]), str(value["agent_id"]), str(value["status"]), tuple(value.get("changed_files") or ()), tuple(value.get("artifacts") or ()), str(value.get("summary") or ""), str(value.get("error") or "")) for key, value in (data.get("results") or {}).items()}
        return MultiAgentRun(items, str(data["run_id"]), str(data.get("state") or "pending"), results, dict(data.get("review") or {}), dict(data.get("integration") or {}), str(data.get("error") or ""))