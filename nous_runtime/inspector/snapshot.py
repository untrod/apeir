# -*- coding: utf-8 -*-
"""Read-only snapshot collectors for Nous Runtime Inspector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nous_runtime.inspector.models import (
    CapabilitySnapshot,
    DeviceSnapshot,
    InspectorSnapshot,
    MemorySnapshot,
    ObservationSnapshot,
    PlanSnapshot,
    ProviderSnapshot,
    RuntimeSnapshot,
    TaskSnapshot,
)

MEMORY_STREAMS = (
    "timeline",
    "events",
    "decisions",
    "summaries",
    "facts",
    "experiences",
    "artifacts",
)

MEMORY_FILES = {
    "timeline": "timeline.jsonl",
    "events": "events.jsonl",
    "decisions": "decisions.jsonl",
    "summaries": "summaries.jsonl",
    "facts": "facts.jsonl",
    "experiences": "experiences.jsonl",
    "artifacts": "artifacts.jsonl",
}


def snapshot() -> InspectorSnapshot:
    """Collect a read-only point-in-time view of runtime state."""
    runtime = _runtime_snapshot()
    ws = _find_workspace()
    if ws:
        runtime.workspace = str(ws)

    providers = _provider_snapshots(runtime)
    capabilities = _capability_snapshots(runtime)
    tasks, plans = _task_and_plan_snapshots(ws, runtime)
    memory = _memory_snapshot(ws)
    observations = _observation_snapshots(ws, memory)
    devices = _device_snapshots(runtime)

    return InspectorSnapshot(
        runtime=runtime,
        providers=providers,
        capabilities=capabilities,
        tasks=tasks,
        plans=plans,
        observations=observations,
        memory=memory,
        devices=devices,
    )


def _runtime_snapshot() -> RuntimeSnapshot:
    rt = RuntimeSnapshot()
    try:
        from nous_runtime import __version__

        rt.version = __version__
    except Exception as exc:
        rt.errors.append(f"version unavailable: {exc}")

    try:
        from nous_runtime.runtime.lifecycle import Runtime

        status = Runtime().status()
        rt.running = bool(getattr(status, "running", False))
        rt.version = str(getattr(status, "version", rt.version))
        rt.demo_mode = bool(getattr(status, "demo_mode", False))
        rt.providers = int(getattr(status, "providers", 0))
        rt.capabilities = int(getattr(status, "capabilities", 0))
        rt.devices = int(getattr(status, "devices", 0))
        rt.jobs_pending = int(getattr(status, "jobs_pending", 0))
        for err in getattr(status, "errors", []) or []:
            rt.errors.append(str(err))
    except Exception as exc:
        rt.errors.append(f"runtime status unavailable: {exc}")
    return rt


def _find_workspace() -> Path | None:
    try:
        from nous_runtime.project.workspace import find_workspace

        return find_workspace()
    except Exception:
        return None


def _provider_snapshots(runtime: RuntimeSnapshot) -> list[ProviderSnapshot]:
    try:
        from nous_runtime.provider.registry import registry

        items = []
        for item in registry.list_all():
            health = item.get("health", {}) if isinstance(item, dict) else {}
            items.append(
                ProviderSnapshot(
                    provider_id=str(item.get("id") or item.get("name") or ""),
                    name=str(item.get("name") or item.get("id") or ""),
                    status=str(health.get("status", "unknown")),
                    capabilities=list(item.get("capabilities") or []),
                )
            )
        return items
    except Exception as exc:
        runtime.errors.append(f"providers unavailable: {exc}")
        return []


def _capability_snapshots(runtime: RuntimeSnapshot) -> list[CapabilitySnapshot]:
    try:
        from nous_runtime.capability.availability import check_availability

        availability = check_availability()
        items: list[CapabilitySnapshot] = []
        for cap in availability.get("available", []):
            items.append(
                CapabilitySnapshot(
                    capability_id=str(cap.get("name", "")),
                    provider_id=str(cap.get("provider", "")),
                    category=str(cap.get("category", "")),
                    risk=str(cap.get("risk", "")),
                    available=True,
                    description=str(cap.get("description", "")),
                )
            )
        for cap in availability.get("unavailable", []):
            items.append(
                CapabilitySnapshot(
                    capability_id=str(cap.get("name", "")),
                    provider_id=str(cap.get("provider", "")),
                    risk=str(cap.get("risk", "")),
                    available=False,
                    reason=str(cap.get("reason", "")),
                )
            )
        return items
    except Exception as exc:
        runtime.errors.append(f"capabilities unavailable: {exc}")
        return []


def _task_and_plan_snapshots(
    workspace: Path | None,
    runtime: RuntimeSnapshot,
) -> tuple[list[TaskSnapshot], list[PlanSnapshot]]:
    if workspace is None:
        return [], []

    tasks_fp = workspace / "tasks.json"
    if not tasks_fp.is_file():
        return [], []

    try:
        data = json.loads(tasks_fp.read_text(encoding="utf-8"))
    except Exception as exc:
        runtime.errors.append(f"tasks unavailable: {exc}")
        return [], []

    tasks: list[TaskSnapshot] = []
    plans: list[PlanSnapshot] = []

    for idx, item in enumerate(_list_or_empty(data.get("tasks"))):
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or item.get("id") or f"task_{idx + 1}")
        plan_id = str(item.get("plan_id") or "")
        obs_ids = item.get("observation_ids") or []
        if not obs_ids and isinstance(item.get("observations"), list):
            obs_ids = [
                str(o.get("observation_id") or o.get("id") or "")
                for o in item["observations"]
                if isinstance(o, dict)
            ]
        tasks.append(
            TaskSnapshot(
                task_id=task_id,
                status=str(item.get("status", "pending")),
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                capability_id=str(item.get("capability_id", "")),
                provider_id=str(item.get("provider_id", "")),
                plan_id=plan_id,
                depends_on=[str(v) for v in _list_or_empty(item.get("depends_on"))],
                observation_ids=[str(v) for v in obs_ids if v],
                error=str(item.get("error", "")),
            )
        )

    for idx, item in enumerate(_list_or_empty(data.get("plans"))):
        if not isinstance(item, dict):
            continue
        task_ids = item.get("task_ids") or []
        if not task_ids and isinstance(item.get("tasks"), list):
            task_ids = [
                str(t.get("task_id") or t.get("id") or "")
                for t in item["tasks"]
                if isinstance(t, dict)
            ]
        plans.append(
            PlanSnapshot(
                plan_id=str(item.get("plan_id") or item.get("id") or f"plan_{idx + 1}"),
                goal_id=str(item.get("goal_id", "")),
                status=str(item.get("status", "")),
                task_ids=[str(v) for v in task_ids if v],
                progress=dict(item.get("progress") or {}),
                error=str(item.get("error", "")),
            )
        )

    return tasks, plans


def _memory_snapshot(workspace: Path | None) -> MemorySnapshot:
    mem = MemorySnapshot(workspace=str(workspace or ""))
    if workspace is None:
        mem.errors.append("No .nous workspace found")
        return mem

    memory_dir = workspace / "memory"
    records_by_stream: dict[str, list[dict[str, Any]]] = {}
    for stream, filename in MEMORY_FILES.items():
        fp = memory_dir / filename
        if not fp.is_file():
            mem.missing_streams.append(stream)
            mem.stream_counts[stream] = 0
            records_by_stream[stream] = []
            continue
        records, invalid = _read_jsonl_strict(fp)
        records_by_stream[stream] = records
        mem.stream_counts[stream] = len(records)
        mem.invalid_records.extend(invalid)

    facts = records_by_stream.get("facts", [])
    mem.active_facts = len(_latest_facts(facts))
    mem.stable_key_conflicts = _stable_key_conflicts(facts)
    mem.broken_supersedes = _broken_supersedes(facts)
    mem.supersedes_cycles = _supersedes_cycles(facts)
    return mem


def _observation_snapshots(
    workspace: Path | None,
    memory: MemorySnapshot,
) -> list[ObservationSnapshot]:
    if workspace is None:
        return []

    observations: dict[str, ObservationSnapshot] = {}
    memory_dir = workspace / "memory"
    for stream, filename in MEMORY_FILES.items():
        fp = memory_dir / filename
        records, _invalid = _read_jsonl_strict(fp)
        for record in records:
            obs_id = str(record.get("observation_id") or "")
            if not obs_id:
                continue
            if obs_id in observations:
                continue
            summary = (
                record.get("detail")
                or record.get("content")
                or record.get("outcome")
                or record.get("description")
                or ""
            )
            observations[obs_id] = ObservationSnapshot(
                observation_id=obs_id,
                status=str(record.get("status") or record.get("outcome") or ""),
                task_id=str(record.get("task_id", "")),
                capability_id=str(record.get("capability_id", "")),
                provider_id=str(record.get("provider_id", "")),
                memory_id=str(record.get("memory_id", "")),
                record_type=str(record.get("record_type") or stream),
                summary=str(summary)[:240],
                error=str(record.get("error") or record.get("error_code") or ""),
            )
    return list(observations.values())


def _device_snapshots(runtime: RuntimeSnapshot) -> list[DeviceSnapshot]:
    try:
        from nous_runtime.compat.devices import list_devices

        devices = []
        for item in list_devices():
            devices.append(
                DeviceSnapshot(
                    device_id=str(item.get("id") or item.get("device_id") or ""),
                    name=str(item.get("name", "")),
                    device_type=str(item.get("device_type", "unknown")),
                    online=bool(item.get("is_online", False)),
                    capabilities=list(item.get("capabilities") or []),
                    last_seen=str(item.get("last_seen", "")),
                )
            )
        return devices
    except Exception as exc:
        runtime.errors.append(f"devices unavailable: {exc}")
        return []


def _read_jsonl_strict(filepath: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not filepath.is_file():
        return [], []

    records: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    try:
        with filepath.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    invalid.append(
                        {
                            "file": filepath.name,
                            "line": line_no,
                            "error": exc.msg,
                        }
                    )
                    continue
                if isinstance(data, dict):
                    records.append(data)
                else:
                    invalid.append(
                        {
                            "file": filepath.name,
                            "line": line_no,
                            "error": "record is not an object",
                        }
                    )
    except Exception as exc:
        invalid.append({"file": filepath.name, "line": 0, "error": str(exc)})
    return records, invalid


def _latest_facts(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for fact in facts:
        stable_key = str(fact.get("stable_key") or fact.get("key") or "")
        if stable_key:
            latest[stable_key] = fact
    return latest


def _stable_key_conflicts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = {}
    for fact in facts:
        key = str(fact.get("stable_key") or fact.get("key") or "")
        if not key:
            continue
        grouped.setdefault(key, set()).add(json.dumps(fact.get("value"), ensure_ascii=False, sort_keys=True))
    return [
        {"stable_key": key, "value_count": len(values)}
        for key, values in sorted(grouped.items())
        if len(values) > 1
    ]


def _broken_supersedes(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {str(f.get("memory_id") or f.get("id") or "") for f in facts}
    broken = []
    for fact in facts:
        supersedes = str(fact.get("supersedes") or "")
        if supersedes and supersedes not in ids:
            broken.append(
                {
                    "memory_id": str(fact.get("memory_id") or fact.get("id") or ""),
                    "supersedes": supersedes,
                    "stable_key": str(fact.get("stable_key") or fact.get("key") or ""),
                }
            )
    return broken


def _supersedes_cycles(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = {
        str(f.get("memory_id") or f.get("id") or ""): str(f.get("supersedes") or "")
        for f in facts
        if f.get("memory_id") or f.get("id")
    }
    cycles: list[dict[str, Any]] = []
    for start in edges:
        seen: set[str] = set()
        node = start
        while node:
            if node in seen:
                cycles.append({"memory_id": start, "cycle_at": node})
                break
            seen.add(node)
            node = edges.get(node, "")
    return cycles


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
