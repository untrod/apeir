"""Workspace path isolation helpers."""

from __future__ import annotations

from pathlib import Path


def normalize_workspace_path(workspace_path: str, candidate_path: str) -> Path:
    workspace = Path(workspace_path).resolve()
    candidate = Path(candidate_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise PermissionError(f"path escapes workspace: {candidate_path}") from exc
    return resolved


def is_within_workspace(workspace_path: str, candidate_path: str) -> bool:
    try:
        normalize_workspace_path(workspace_path, candidate_path)
        return True
    except PermissionError:
        return False
