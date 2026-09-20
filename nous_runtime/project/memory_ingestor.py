# -*- coding: utf-8 -*-
"""Observation-to-memory ingestion."""

from __future__ import annotations

from pathlib import Path as _Path
from typing import Any

from nous_runtime.planner.observation import Observation
from nous_runtime.project.memory import add_memory_record
from nous_runtime.project.memory_records import (
    MemoryArtifactRef,
    MemoryEvent,
    MemoryExperience,
    MemoryFact,
    MemoryRecord,
    MemorySummary,
)


class MemoryIngestor:
    """Rule-based Observation ingestion for project memory."""

    def __init__(self, workspace: str | _Path):
        self.workspace = _Path(workspace)
        self.project_id = self._project_id()

    def ingest(self, observation: Observation) -> list[dict[str, Any]]:
        """Persist memory records extracted from an Observation."""
        if not isinstance(observation, Observation):
            raise TypeError("MemoryIngestor accepts only Observation objects")

        records = self.extract(observation)
        persisted: list[dict[str, Any]] = []
        for record in records:
            persisted.append(add_memory_record(self.workspace, record))
        return persisted

    def extract(self, observation: Observation) -> list[MemoryRecord]:
        """Return deterministic memory records for an Observation."""
        records: list[MemoryRecord] = []
        tool = observation.tool

        if tool == "project.memory":
            return []
        if observation.status == "failed":
            records.extend(self._failure_records(observation))
            return records

        if tool == "project.scan":
            records.extend(self._project_scan_records(observation))
        elif tool == "task.execute":
            records.extend(self._task_records(observation))
        elif tool == "plan.execute":
            records.extend(self._plan_records(observation))
        elif observation.metadata.get("approval") == "waiting" or observation.status == "skipped":
            records.append(self._event(observation, "waiting_approval", "Approval required"))
        else:
            records.append(self._event(observation, f"{tool}_completed", f"{tool} completed"))

        records.extend(self._artifact_records(observation))
        return records

    def _project_scan_records(self, observation: Observation) -> list[MemoryRecord]:
        data = observation.data or {}
        files = data.get("files", 0)
        total_size_kb = data.get("total_size_kb", 0)
        languages = data.get("languages", {})
        records: list[MemoryRecord] = [
            self._event(observation, "project_scan_completed", f"Indexed {files} files"),
            self._fact(observation, "project.files.total", files, ["project", "scan"]),
            self._fact(observation, "project.size_kb.total", total_size_kb, ["project", "scan"]),
        ]
        if isinstance(languages, dict):
            for name, count in list(languages.items())[:20]:
                records.append(
                    self._fact(
                        observation,
                        f"project.language.{name}.files",
                        count,
                        ["project", "language", str(name)],
                    )
                )
        return records

    def _task_records(self, observation: Observation) -> list[MemoryRecord]:
        data = observation.data or {}
        task_id = str(data.get("task_id") or observation.metadata.get("task_id", ""))
        capability_id = str(data.get("capability_id") or observation.capability)
        result = data.get("result", {})
        summary = _summarize_payload(result)
        return [
            self._event(observation, "task_completed", f"Task {task_id} completed", task_id=task_id),
            MemorySummary(
                source_type="observation",
                project_id=self.project_id,
                task_id=task_id,
                observation_id=observation.observation_id,
                capability_id=capability_id,
                provider_id=str(observation.metadata.get("provider_id", "")),
                title=f"Task {task_id} result",
                content=summary,
                tags=["task", capability_id] if capability_id else ["task"],
                metadata={"tool": observation.tool},
            ),
        ]

    def _plan_records(self, observation: Observation) -> list[MemoryRecord]:
        data = observation.data or {}
        progress = data.get("progress", {}) if isinstance(data, dict) else {}
        plan_id = str(data.get("plan_id") or observation.metadata.get("plan_id", ""))
        done = progress.get("done", 0)
        total = progress.get("total", 0)
        failed = progress.get("failed", 0)
        return [
            self._event(observation, "task_graph_completed", f"Plan {plan_id}: {done}/{total} done, {failed} failed"),
            MemorySummary(
                source_type="observation",
                project_id=self.project_id,
                task_graph_id=plan_id,
                observation_id=observation.observation_id,
                title=f"Plan {plan_id} execution",
                content=f"Plan execution completed with {done}/{total} tasks done and {failed} failed.",
                tags=["plan", "task_graph"],
                metadata={"progress": progress},
            ),
        ]

    def _failure_records(self, observation: Observation) -> list[MemoryRecord]:
        error = "; ".join(observation.errors) if observation.errors else "execution failed"
        records: list[MemoryRecord] = [
            self._event(observation, f"{observation.tool}_failed", error),
        ]
        provider_id = str(observation.metadata.get("provider_id", ""))
        capability_id = observation.capability
        if provider_id or capability_id:
            records.append(
                MemoryExperience(
                    source_type="observation",
                    project_id=self.project_id,
                    task_id=str(observation.metadata.get("task_id", "")),
                    observation_id=observation.observation_id,
                    capability_id=capability_id,
                    provider_id=provider_id,
                    outcome="failed",
                    error_code=str(observation.metadata.get("error_code", "")),
                    tags=["experience", "failure", capability_id] if capability_id else ["experience", "failure"],
                )
            )
        return records

    def _artifact_records(self, observation: Observation) -> list[MemoryRecord]:
        data = observation.data or {}
        artifacts = data.get("artifacts", [])
        if not artifacts and data.get("artifact_id"):
            artifacts = [data]
        if not isinstance(artifacts, list):
            return []
        records: list[MemoryRecord] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id", artifact.get("id", "")))
            path = str(artifact.get("path", ""))
            if not artifact_id and not path:
                continue
            records.append(
                MemoryArtifactRef(
                    source_type="artifact",
                    project_id=self.project_id,
                    task_id=str(observation.metadata.get("task_id", "")),
                    observation_id=observation.observation_id,
                    capability_id=observation.capability,
                    artifact_id=artifact_id,
                    path=_safe_path(path),
                    kind=str(artifact.get("kind", "")),
                    description=_summarize_payload(artifact),
                    tags=["artifact"],
                )
            )
        return records

    def _event(self, observation: Observation, event_type: str, detail: str, task_id: str = "") -> MemoryEvent:
        return MemoryEvent(
            source_type="observation",
            project_id=self.project_id,
            task_id=task_id or str(observation.metadata.get("task_id", "")),
            task_graph_id=str(observation.metadata.get("plan_id", "")),
            observation_id=observation.observation_id,
            capability_id=observation.capability,
            provider_id=str(observation.metadata.get("provider_id", "")),
            event_type=event_type,
            detail=_compact_text(detail),
            tags=["event", observation.tool],
            metadata={"tool": observation.tool, "status": observation.status},
        )

    def _fact(self, observation: Observation, key: str, value: Any, tags: list[str]) -> MemoryFact:
        return MemoryFact(
            source_type="observation",
            project_id=self.project_id,
            observation_id=observation.observation_id,
            capability_id=observation.capability,
            key=key,
            stable_key=key,
            value=_redact_value(value),
            tags=tags,
            metadata={"tool": observation.tool},
        )

    def _project_id(self) -> str:
        project_json = self.workspace / "project.json"
        if project_json.is_file():
            try:
                import json

                data = json.loads(project_json.read_text(encoding="utf-8"))
                return str(data.get("name") or self.workspace.parent.name)
            except Exception:
                pass
        return self.workspace.parent.name


def ingest_observation(workspace: str | _Path, observation: Observation) -> list[dict[str, Any]]:
    """Convenience wrapper for one Observation."""
    return MemoryIngestor(workspace).ingest(observation)


def _summarize_payload(value: Any, limit: int = 500) -> str:
    import json

    if isinstance(value, dict):
        compact = {
            k: _redact_value(v)
            for k, v in value.items()
            if str(k).lower() not in {"raw", "content", "prompt", "response"}
        }
        text = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    else:
        text = str(_redact_value(value))
    return _compact_text(text, limit=limit)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k).lower().replace("-", "_")
            if any(part in key for part in ("api_key", "apikey", "token", "secret", "password", "private_key")):
                result[k] = "<redacted>"
            else:
                result[k] = _redact_value(v)
        return result
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        return _compact_text(value)
    return value


def _compact_text(value: str, limit: int = 500) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _safe_path(path: str) -> str:
    p = str(path)
    if p.startswith("/") or p.startswith("\\\\") or (len(p) > 2 and p[1:3] in (":\\", ":/")):
        return _Path(p).name
    return p
