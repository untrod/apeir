"""Workspace path isolation helpers."""

from __future__ import annotations

import stat
from pathlib import Path


class WorkspaceHardLinkError(PermissionError):
    """An ordinary workspace path aliases another regular-file name."""


def normalize_workspace_path(
    workspace_path: str,
    candidate_path: str,
    *,
    protect_runtime_state: bool = False,
) -> Path:
    workspace = Path(workspace_path).resolve()
    candidate = Path(candidate_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise PermissionError(f"path escapes workspace: {candidate_path}") from exc
    if protect_runtime_state and any(
        part.casefold() in {".nous", ".git"} for part in relative.parts
    ):
        raise PermissionError("Runtime-private paths are not ordinary workspace data.")
    if protect_runtime_state:
        try:
            info = resolved.stat()
        except FileNotFoundError:
            pass  # Preserve admission of not-yet-created ordinary write targets.
        else:
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise WorkspaceHardLinkError(
                    "Ordinary workspace data requires single-link files."
                )
    return resolved


def is_within_workspace(workspace_path: str, candidate_path: str) -> bool:
    try:
        normalize_workspace_path(workspace_path, candidate_path)
        return True
    except PermissionError:
        return False
