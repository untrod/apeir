# -*- coding: utf-8 -*-
"""
Project Workspace — .nous/ directory detection, creation, and management.

The .nous/ workspace is the project-level data store. It lives in the
project root and contains everything that belongs to the project:
configuration, goals, tasks, local memory, file index, traces, and
artifacts.

Usage:
    from nous_runtime.project.workspace import find_workspace, init_workspace

    ws = find_workspace()          # walk up from cwd
    if ws is None:
        ws = init_workspace()      # create .nous/ in current directory
"""

from __future__ import annotations

import json as _json
import logging
import os as _os
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path
from typing import Any


# Constants

NOUS_DIR = ".nous"


def default_workspace_path(*parts: str) -> _Path:
    """Return a path below the compatibility workspace directory.

    The on-disk name remains stable for existing projects, but callers use this
    helper so the compatibility identifier is owned in one place.
    """
    return _Path(NOUS_DIR).joinpath(*parts)

DEFAULT_STRUCTURE: dict[str, list[str]] = {
    "memory": [
        "timeline.jsonl",
        "events.jsonl",
        "decisions.jsonl",
        "summaries.jsonl",
        "facts.jsonl",
        "experiences.jsonl",
        "artifacts.jsonl",
    ],
    "index": ["files.json"],
    "traces": [],
    "artifacts": [],
}


# Detection

def find_workspace(start_dir: str | _Path | None = None) -> _Path | None:
    """
    Walk up from *start_dir* (default: cwd) looking for a .nous/ directory.

    Returns the absolute Path to the .nous/ directory, or None if no
    workspace was found before hitting the filesystem root.
    """
    configured_root = _os.environ.get("NOUS_WORKSPACE_ROOT") if start_dir is None else ""
    if configured_root:
        candidate = _Path(configured_root).expanduser().resolve() / NOUS_DIR
        return candidate if candidate.is_dir() else None

    current = _Path(start_dir).resolve() if start_dir else _Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / NOUS_DIR
        if candidate.is_dir():
            return candidate
    return None


# Initialisation

def init_workspace(path: str | _Path | None = None) -> _Path:
    """
    Create a .nous/ workspace in *path* (default: cwd).

    Directory structure::

        .nous/
        ├── project.json
        ├── config.json
        ├── goals.json
        ├── tasks.json
        ├── memory/
        │   ├── timeline.jsonl
        │   ├── decisions.jsonl
        │   ├── summaries.jsonl
        │   └── facts.jsonl
        ├── index/
        │   └── files.json
        ├── traces/
        ├── artifacts/
        └── history

    Existing files are never overwritten.  Returns the Path to the
    .nous/ directory.
    """
    configured_root = _os.environ.get("NOUS_WORKSPACE_ROOT") if path is None else ""
    root = (
        _Path(path).resolve()
        if path
        else _Path(configured_root).expanduser().resolve()
        if configured_root
        else _Path.cwd()
    )
    nous_dir = root / NOUS_DIR

    # B1 Governance: authorize workspace creation before mutating disk.
    try:
        from nous_runtime.governance import (
            ActionProposal,
            AuthorizationContext,
            get_gate,
        )
        from nous_runtime.governance.runtime_mode import should_fail_closed
        import getpass as _gp

        proposal = ActionProposal(
            action_type="workspace.create",
            capability_id="workspace.init",
            target_workspace=str(root),
            affected_resources=(str(nous_dir),),
            side_effect_class="local_write",
            reversibility="reversible",
        )
        context = AuthorizationContext(
            subject_type="user",
            subject_id=f"{_gp.getuser()}@localhost",
            authn_method="cli_os_user",
            authn_confidence=0.8,
            session_locality="local",
        )
        gate = get_gate()
        decision = gate.evaluate(proposal, context)

        if decision.action_mode == "DENY":
            _log = logging.getLogger("nous.project.workspace")
            if should_fail_closed(surface="local_cli"):
                raise PermissionError(f"Workspace creation authorization denied: {decision.reason_message}")
            _log.warning("Workspace creation authorization denied: %s", decision.reason_message)
    except Exception as e:
        from nous_runtime.governance.runtime_mode import should_fail_closed
        _log_gate = logging.getLogger("nous.project.workspace")
        if should_fail_closed(surface="local_cli"):
            raise
        _log_gate.debug("Gate evaluation skipped in compatibility mode: %s", e)

    nous_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectories + placeholder files
    for subdir, files in DEFAULT_STRUCTURE.items():
        sd = nous_dir / subdir
        sd.mkdir(parents=True, exist_ok=True)
        for fname in files:
            fp = sd / fname
            if not fp.exists():
                fp.write_text("", encoding="utf-8")

    # history file (plain text, one command per line)
    _touch(nous_dir / "history")

    # project.json — create once, never overwrite
    _write_json_if_missing(
        nous_dir / "project.json",
        {
            "name": root.name,
            "root": str(root),
            "created": _utc_now(),
        },
    )

    # config.json — create once, never overwrite
    _write_json_if_missing(nous_dir / "config.json", {})

    # goals.json
    _write_json_if_missing(nous_dir / "goals.json", {"goals": []})

    # tasks.json
    _write_json_if_missing(nous_dir / "tasks.json", {"tasks": []})

    # Timeline: record creation
    from nous_runtime.project.memory import add_event

    add_event(str(nous_dir), "workspace_created", f"Initialized .nous/ in {root}")

    return nous_dir


# Read helpers

def read_project_config(workspace: str | _Path) -> dict[str, Any]:
    """Read project.json from a .nous/ workspace."""
    fp = _Path(workspace) / "project.json"
    if fp.is_file():
        return _json.loads(fp.read_text(encoding="utf-8"))
    return {}


def workspace_root(workspace: str | _Path) -> _Path:
    """Return the project root directory (parent of .nous/)."""
    return _Path(workspace).parent


# Internal helpers

def _write_json_if_missing(filepath: _Path, data: Any) -> bool:
    """Write *data* as JSON only if *filepath* does not already exist."""
    if filepath.exists():
        return False
    _write_json_atomic(filepath, data)
    return True


def _write_json_atomic(filepath: _Path, data: Any) -> None:
    """Atomically write JSON via temp-file + os.replace."""
    tmp = _Path(str(filepath) + ".tmp")
    tmp.write_text(
        _json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _os.replace(str(tmp), str(filepath))


def _touch(filepath: _Path) -> None:
    """Create an empty file if it does not exist."""
    if not filepath.exists():
        filepath.write_text("", encoding="utf-8")


def _utc_now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
