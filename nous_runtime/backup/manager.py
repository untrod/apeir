# -*- coding: utf-8 -*-
"""Backup Manager — scheduled snapshots of all runtime state."""
from __future__ import annotations
import logging
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.backup")

class BackupManager:
    """Creates and manages backups of Nous runtime state."""
    def __init__(self, workspace: str = ""):
        self._workspace = Path(workspace) if workspace else Path.cwd() / ".nous"
        self._backup_dir = self._workspace / "backups"

    def create_backup(self, label: str = "") -> dict[str, Any]:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        name = f"backup-{ts}" if not label else f"backup-{label}-{ts}"
        backup_path = self._backup_dir / name
        backup_path.mkdir(parents=True, exist_ok=True)
        files_backed_up = 0
        errors = []
        # Backup all .db and .jsonl files
        for pattern in ["*.db", "*.jsonl", "*.json"]:
            for f in self._workspace.glob(pattern):
                try:
                    dest = backup_path / f.name
                    shutil.copy2(f, dest)
                    files_backed_up += 1
                except Exception as exc:
                    errors.append(str(exc))
        # Context snapshot
        try:
            from nous_runtime.context.snapshot import create_snapshot
            create_snapshot(workspace=str(self._workspace), intent=f"backup_{name}", persist=True)
        except Exception as exc:
            errors.append(f"context_snapshot: {exc}")
        # Manifest
        manifest = {
            "backup_name": name, "timestamp": ts,
            "workspace": str(self._workspace), "files_backed_up": files_backed_up,
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
        backup_path = self._backup_dir / backup_name
        if not backup_path.exists():
            return {"success": False, "error": f"Backup not found: {backup_name}"}
        restored = 0
        for f in backup_path.glob("*"):
            if f.name == "manifest.json":
                continue
            try:
                shutil.copy2(f, self._workspace / f.name)
                restored += 1
            except Exception as exc:
                _log.error("Failed to restore %s: %s", f.name, exc)
        _log.info("Restored %d files from %s", restored, backup_name)
        return {"success": True, "backup_name": backup_name, "files_restored": restored}
