# -*- coding: utf-8 -*-
"""Backup Manager — scheduled snapshots of all runtime state."""

from __future__ import annotations
import logging
import json
import shutil
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.security.private_files import (
    restrict_owner_only_file,
    validate_private_database_path,
)

_log = logging.getLogger("nous.backup")


def _snapshot_database(source: Path, destination: Path) -> None:
    """Copy a committed SQLite snapshot using its own transaction boundary."""
    validate_private_database_path(source)
    validate_private_database_path(destination)
    started = time.monotonic()

    def progress(_status, _remaining, _total):
        if time.monotonic() - started >= 5:
            raise TimeoutError("SQLite backup exceeded its five-second deadline")

    with closing(
        sqlite3.connect(source.absolute().as_uri() + "?mode=ro", uri=True)
    ) as reader:
        with closing(sqlite3.connect(destination)) as snapshot:
            restrict_owner_only_file(destination, subject="SQLite backup")
            reader.backup(snapshot, pages=256, progress=progress, sleep=0.05)


def _copy_database(source: Path, destination: Path) -> None:
    """Publish a self-contained backup only after the snapshot is complete."""
    descriptor, temporary = tempfile.mkstemp(
        prefix=".sqlite-backup-", dir=destination.parent
    )
    os.close(descriptor)
    staged = Path(temporary)
    try:
        _snapshot_database(source, staged)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


class BackupManager:
    """Creates and manages backups of Nous runtime state."""

    def __init__(self, workspace: str = ""):
        self._workspace = Path(workspace) if workspace else Path.cwd() / ".nous"
        self._backup_dir = self._workspace / "backups"

    def create_backup(self, label: str = "") -> dict[str, Any]:
        if label in {".", ".."} or any(
            char in label for char in ("/", "\\", ":", "\0")
        ):
            raise ValueError("Backup label must be a single name")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        name = f"backup-{ts}" if not label else f"backup-{label}-{ts}"
        backup_path = self._backup_dir / name
        # A repeated label in the same second must not overwrite an older copy.
        backup_path.mkdir(parents=True, exist_ok=False)
        files_backed_up = 0
        errors = []
        # Backup all .db and .jsonl files
        for pattern in ["*.db", "*.jsonl", "*.json"]:
            for f in self._workspace.glob(pattern):
                try:
                    dest = backup_path / f.name
                    if f.suffix == ".db":
                        _copy_database(f, dest)
                    else:
                        shutil.copy2(f, dest)
                    files_backed_up += 1
                except Exception as exc:
                    errors.append(str(exc))
        # Context snapshot
        try:
            from nous_runtime.context.snapshot import create_snapshot

            create_snapshot(
                workspace=str(self._workspace), intent=f"backup_{name}", persist=True
            )
        except Exception as exc:
            errors.append(f"context_snapshot: {exc}")
        # Manifest
        manifest = {
            "backup_name": name,
            "timestamp": ts,
            "workspace": str(self._workspace),
            "files_backed_up": files_backed_up,
            "errors": errors,
        }
        (backup_path / "manifest.json").write_text(json.dumps(manifest, indent=2))
        _log.info("Backup created: %s (%d files)", name, files_backed_up)
        return manifest

    def list_backups(self) -> list[dict[str, Any]]:
        if not self._backup_dir.exists():
            return []
        backups = []
        for d in sorted(self._backup_dir.iterdir(), reverse=True):
            if d.is_dir():
                mf = d / "manifest.json"
                if mf.exists():
                    backups.append(json.loads(mf.read_text()))
        return backups

    def restore_backup(self, backup_name: str) -> dict[str, Any]:
        if (
            not backup_name
            or backup_name in {".", ".."}
            or any(char in backup_name for char in ("/", "\\", ":", "\0"))
        ):
            return {"success": False, "error": "Backup must be a single name"}
        backup_path = self._backup_dir / backup_name
        if not backup_path.exists():
            return {"success": False, "error": f"Backup not found: {backup_name}"}
        restored = 0
        errors = []
        for f in backup_path.glob("*"):
            if f.name == "manifest.json":
                continue
            try:
                if f.suffix == ".db":
                    # Never replace a live SQLite inode while its WAL still
                    # refers to the original database. SQLite owns the restore
                    # transaction; an active writer is bounded and fails closed.
                    _snapshot_database(f, self._workspace / f.name)
                else:
                    shutil.copy2(f, self._workspace / f.name)
                restored += 1
            except Exception as exc:
                errors.append(f"{f.name}: {type(exc).__name__}")
                _log.error("Failed to restore %s: %s", f.name, exc)
        _log.info("Restored %d files from %s", restored, backup_name)
        return {
            "success": not errors,
            "backup_name": backup_name,
            "files_restored": restored,
            "errors": errors,
        }
