# -*- coding: utf-8 -*-
"""WorkspaceGuard — enforces filesystem boundaries for agent execution."""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceGuard:
    """Enforces that all file operations stay within the approved workspace.

    Requirements:
    - Resolve and normalize all paths
    - Reject path traversal (..)
    - Reject writes outside the workspace
    - Reject symlink escapes
    """

    def __init__(self, workspace_root: str):
        if not workspace_root:
            raise ValueError("workspace_root is required")
        self._root = str(Path(workspace_root).resolve(strict=False))
        if not os.path.isdir(self._root):
            raise ValueError(f"Workspace root does not exist: {self._root}")

    @property
    def root(self) -> str:
        return self._root

    def resolve(self, path: str) -> str:
        """Resolve a path relative to the workspace root."""
        if os.path.isabs(path):
            resolved = str(Path(path).resolve(strict=False))
        else:
            resolved = str((Path(self._root) / path).resolve(strict=False))
        return resolved

    def is_within_workspace(self, path: str) -> bool:
        """Check if a path is within the workspace root."""
        resolved = str(Path(path).resolve(strict=False))
        try:
            Path(resolved).relative_to(self._root)
            return True
        except ValueError:
            return False

    def validate_path(self, path: str, *, allow_nonexistent: bool = False) -> str:
        """Validate and normalize a path.

        Returns the resolved path if valid.
        Raises ValueError if path traversal or workspace escape is detected.
        """
        if ".." in Path(path).parts:
            raise ValueError(f"Path traversal detected: {path}")

        resolved = self.resolve(path)

        if not self.is_within_workspace(resolved):
            raise ValueError(f"Path escapes workspace: {path} -> {resolved}")

        if not allow_nonexistent and not os.path.exists(resolved):
            raise ValueError(f"Path does not exist: {resolved}")

        return resolved

    def validate_command_args(self, args: tuple[str, ...]) -> tuple[str, ...]:
        """Check all file arguments in a command for workspace violations."""
        for arg in args:
            # Skip flags and non-path arguments
            if arg.startswith("-"):
                continue
            # Check if argument looks like a file path
            if "/" in arg or "\\" in arg or os.path.sep in arg:
                self.validate_path(arg, allow_nonexistent=True)
            elif os.path.exists(os.path.join(self._root, arg)):
                self.validate_path(arg, allow_nonexistent=True)
        return args

    def allowed_files_for_command(
        self, command_args: tuple[str, ...]
    ) -> list[str]:
        """Return the set of files a command would affect."""
        affected: list[str] = []
        for arg in command_args:
            if arg.startswith("-"):
                continue
            try:
                resolved = self.validate_path(arg, allow_nonexistent=True)
                affected.append(resolved)
            except ValueError:
                pass
        return affected
