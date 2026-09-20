# -*- coding: utf-8 -*-
"""
Tool Execution Pipeline — intent → tool → Observation → LLM.

Before invoking the LLM, the Runtime checks whether the user's request
matches a local capability.  If it does, the tool executes first and
produces a structured Observation.  That Observation is then assembled
into the LLM prompt as context.

Architecture:
    User Input → Intent Detection → Tool Execution → Observation
    → Context Assembly → LLM Invocation → Response
"""

from __future__ import annotations

import json as _json
import os as _os
import time as _time
from pathlib import Path as _Path
from typing import Any

from nous_runtime.planner.observation import Observation


# Intent → Tool mapping

INTENT_MAP: list[tuple[list[str], list[str], str]] = [
    (["扫描", "scan"],            ["scan project", "index project"], "project.scan"),
    (["总结", "概述", "summar"],  ["summarize project", "project summary"], "project.summary"),
    (["任务", "task", "todo"],    ["show tasks", "list tasks", "what tasks"], "project.tasks"),
    (["记忆", "memory", "回忆"],   ["show memory", "project memory", "timeline"], "project.memory"),
    (["readme", "自述"],          ["read readme", "show readme"], "tool.file.read"),
    (["搜索", "search", "find", "查找"], ["search project", "find in project"], "tool.project.search"),
]


def detect_intent(text: str) -> str | None:
    """Return the first matching intent name, or None."""
    lower = text.lower()
    for cn_keywords, en_keywords, intent in INTENT_MAP:
        for kw in cn_keywords:
            if kw in lower:
                return intent
        for kw in en_keywords:
            if kw in lower:
                return intent
    return None


def execute_tool(intent: str) -> Observation:
    """Execute a local tool and return a structured Observation."""
    start = _time.time()
    try:
        if intent == "project.scan":
            obs = _tool_project_scan()
        elif intent == "project.summary":
            obs = _tool_project_summary()
        elif intent == "project.tasks":
            obs = _tool_project_tasks()
        elif intent == "project.memory":
            obs = _tool_project_memory()
        elif intent == "tool.file.read":
            obs = _tool_file_read()
        elif intent == "tool.project.search":
            obs = _tool_project_search()
        else:
            obs = Observation.failure(intent, [f"Unknown intent: {intent}"])
    except Exception as e:
        obs = Observation.failure(intent, [str(e)])
    obs.duration_ms = (_time.time() - start) * 1000
    _persist_observation(obs)
    return obs


def build_llm_prompt(intent: str, observation: Observation,
                     user_text: str) -> str:
    """Assemble a structured prompt from the Observation and user request."""
    obs_block = observation.to_context_block()
    return (
        f"The Runtime has executed a local capability: {intent}\n\n"
        f"{obs_block}\n\n"
        f"User request: {user_text}\n\n"
        f"Please respond based on the Runtime Observation above."
    )


# Tool implementations

def _tool_project_scan() -> Observation:
    from nous_runtime.project.workspace import find_workspace, init_workspace
    ws = find_workspace()
    if ws is None:
        ws = init_workspace()

    from nous_runtime.project.scan import scan_project
    root = str(ws.parent)
    summary = scan_project(root)

    files_index = _load_json(ws / "index" / "files.json")
    languages: dict[str, int] = {}
    for f in files_index if isinstance(files_index, list) else []:
        if isinstance(f, dict):
            ft = f.get("type", "unknown")
            languages[ft] = languages.get(ft, 0) + 1

    return Observation.success("project.scan", {
        "workspace": root,
        "files": summary.get("total_files", 0),
        "total_size_kb": summary.get("total_size_kb", 0),
        "languages": dict(sorted(languages.items(),
                                 key=lambda x: x[1], reverse=True)),
        "scanned_at": summary.get("scanned_at", ""),
    })


def _tool_project_summary() -> Observation:
    from nous_runtime.project.workspace import find_workspace, init_workspace
    ws = find_workspace()
    if ws is None:
        ws = init_workspace()

    root = str(ws.parent)

    files_index = _load_json(ws / "index" / "files.json")
    file_count = len(files_index) if isinstance(files_index, list) else 0

    tasks_data = _load_json(ws / "tasks.json")
    tasks = tasks_data.get("tasks", []) if isinstance(tasks_data, dict) else []

    from nous_runtime.project.memory import read_recent
    events = read_recent(str(ws), "timeline", limit=10)
    recent = [{"type": e.get("type", ""), "detail": e.get("detail", "")}
              for e in events]

    if file_count == 0:
        from nous_runtime.project.scan import scan_project
        scan_project(root)
        files_index = _load_json(ws / "index" / "files.json")
        file_count = len(files_index) if isinstance(files_index, list) else 0

    return Observation.success("project.summary", {
        "workspace": root,
        "project": ws.name if ws else "",
        "files": file_count,
        "pending_tasks": len(tasks),
        "recent_events": len(recent),
        "last_events": recent[-3:] if recent else [],
        "tasks": [t.get("title", "") for t in tasks[:5]
                  if isinstance(t, dict)],
    })


def _tool_project_tasks() -> Observation:
    from nous_runtime.project.workspace import find_workspace
    ws = find_workspace()
    tasks: list[dict] = []
    if ws:
        data = _load_json(ws / "tasks.json")
        tasks = data.get("tasks", []) if isinstance(data, dict) else []

    return Observation.success("project.tasks", {
        "total": len(tasks),
        "tasks": tasks,
    })


def _tool_project_memory() -> Observation:
    from nous_runtime.project.workspace import find_workspace
    ws = find_workspace()
    events: list[dict] = []
    if ws:
        from nous_runtime.project.memory import read_recent
        events = read_recent(str(ws), "timeline", limit=20)

    return Observation.success("project.memory", {
        "total_events": len(events),
        "recent": [{"type": e.get("type", ""),
                     "detail": e.get("detail", ""),
                     "timestamp": e.get("timestamp", "")}
                   for e in events],
    })


def _tool_file_read() -> Observation:
    from nous_runtime.project.workspace import find_workspace
    ws = find_workspace()
    root = ws.parent if ws else _Path.cwd()

    readme = root / "README.md"
    if readme.is_file():
        content = readme.read_text(encoding="utf-8")[:2000]
        return Observation.success("tool.file.read", {
            "file": "README.md",
            "size": readme.stat().st_size,
            "content": content,
        })
    return Observation.failure("tool.file.read",
                                ["README.md not found"])


def _tool_project_search() -> Observation:
    from nous_runtime.project.workspace import find_workspace
    ws = find_workspace()
    root = ws.parent if ws else _Path.cwd()

    markers: list[dict] = []
    for dirpath, dirnames, filenames in _os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and d not in ("node_modules", "__pycache__",
                                     ".git", ".nous", "build", "dist")]
        for fname in filenames:
            if fname.endswith((".py", ".md", ".js", ".ts", ".json", ".yaml")):
                fp = _Path(dirpath) / fname
                try:
                    for i, line in enumerate(fp.read_text(
                        encoding="utf-8", errors="ignore"
                    ).split("\n"), 1):
                        if "TODO" in line or "FIXME" in line:
                            markers.append({
                                "file": str(fp.relative_to(root)),
                                "line": i,
                                "text": line.strip()[:120],
                            })
                            if len(markers) >= 20:
                                break
                except Exception:
                    continue
            if len(markers) >= 20:
                break

    return Observation.success("tool.project.search", {
        "query": "TODO/FIXME",
        "total": len(markers),
        "results": markers,
    })


# Helpers

def _load_json(path: _Path) -> Any:
    try:
        if path.is_file():
            return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _persist_observation(obs: Observation) -> None:
    if obs.tool == "project.memory":
        return
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws is None:
            return
        from nous_runtime.project.memory_ingestor import ingest_observation
        ingest_observation(str(ws), obs)
    except Exception:
        pass
