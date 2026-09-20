# -*- coding: utf-8 -*-
"""
Project Scanner — index project files into .nous/index/files.json.

Scans the project tree, excluding VCS, build artefacts, and virtual
environments.  Writes a flat JSON index with one entry per file.

Usage:
    from nous_runtime.project.scan import scan_project

    summary = scan_project()
    print(summary["total_files"], "files indexed")
"""

from __future__ import annotations

import json as _json
import os as _os
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path
from typing import Any


# Directories to skip during scanning
EXCLUDE_DIRS: set[str] = {
    ".git",
    ".nous",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "*.egg-info",
}

# File extensions → human-readable type labels
_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".txt": "text",
    ".csv": "csv",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "shell",
    ".bat": "batch",
    ".ps1": "powershell",
    ".cfg": "config",
    ".ini": "config",
    ".env": "env",
    ".gitignore": "gitignore",
    ".dockerfile": "dockerfile",
    ".xml": "xml",
    ".svg": "svg",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".ico": "image",
    ".pdf": "pdf",
    ".ipynb": "notebook",
    ".lock": "lockfile",
}


def scan_project(
    root: str | _Path | None = None,
    output_path: str | _Path | None = None,
) -> dict[str, Any]:
    """
    Walk the project tree and write an index to files.json.

    Args:
        root: Project root directory (default: cwd).
        output_path: Path for the output JSON (default: .nous/index/files.json).

    Returns:
        Summary dict: {"total_files": N, "total_size_kb": N, "types": {...}}
    """
    root = _Path(root).resolve() if root else _Path.cwd()

    # Resolve output path
    if output_path:
        out = _Path(output_path)
    else:
        out = root / ".nous" / "index" / "files.json"
    _os.makedirs(out.parent, exist_ok=True)

    files: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    total_size = 0

    for dirpath, dirnames, filenames in _os.walk(root):
        # Prune excluded directories in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS and not d.endswith(".egg-info")
        ]

        # Skip hidden directories (except .nous — already excluded above)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        rel_dir = _Path(dirpath).relative_to(root)

        for fname in filenames:
            # Skip hidden files (but keep .env, .gitignore etc.)
            if fname.startswith(".") and fname not in (
                ".env", ".env.example", ".gitignore", ".gitattributes",
                ".editorconfig", ".pre-commit-config.yaml",
            ):
                continue

            full = _Path(dirpath) / fname
            try:
                stat = full.stat()
            except OSError:
                continue

            ext = full.suffix.lower()
            ftype = _EXT_MAP.get(ext, ext.lstrip(".") if ext else "unknown")

            rel_path = str(rel_dir / fname) if str(rel_dir) != "." else fname

            entry: dict[str, Any] = {
                "path": rel_path.replace("\\", "/"),
                "type": ftype,
                "size": stat.st_size,
                "modified": _dt.fromtimestamp(
                    stat.st_mtime, tz=_tz.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            files.append(entry)
            type_counts[ftype] = type_counts.get(ftype, 0) + 1
            total_size += stat.st_size

    # Sort by path for determinism
    files.sort(key=lambda x: x["path"])

    # Atomic write
    tmp = _Path(str(out) + ".tmp")
    tmp.write_text(
        _json.dumps(files, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _os.replace(str(tmp), str(out))

    summary: dict[str, Any] = {
        "total_files": len(files),
        "total_size_kb": round(total_size / 1024, 1),
        "types": dict(
            sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "scanned_at": _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Timeline event
    try:
        from nous_runtime.project.workspace import find_workspace

        ws = find_workspace(root)
        if ws:
            from nous_runtime.project.memory import add_event

            add_event(
                str(ws), "scan_completed",
                f"Indexed {summary['total_files']} files "
                f"({summary['total_size_kb']} KB) in {root}",
            )
    except Exception:
        pass

    return summary
