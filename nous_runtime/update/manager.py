# -*- coding: utf-8 -*-
"""Update Manager — version checking, upgrade, rollback."""
from __future__ import annotations
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.version import __version__ as CURRENT_VERSION

_log = logging.getLogger("nous.update")

class UpdateManager:
    """Manages Nous Runtime version upgrades and rollbacks."""
    def __init__(self, workspace: str = ""):
        self._workspace = Path(workspace) if workspace else Path.cwd() / ".nous"
        self._state_file = self._workspace / "update_state.json"

    def current_version(self) -> str:
        return CURRENT_VERSION

    def check_for_updates(self) -> dict[str, Any]:
        """Check if a newer version is available."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "nous-runtime"],
                capture_output=True, text=True, timeout=30,
            )
            return {"current": CURRENT_VERSION, "check_ok": result.returncode == 0}
        except Exception:
            return {"current": CURRENT_VERSION, "check_ok": False, "error": "pip index failed"}

    def upgrade(self) -> dict[str, Any]:
        """Upgrade to latest version."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "nous-runtime"],
                capture_output=True, text=True, timeout=120,
            )
            ok = result.returncode == 0
            self._save_state({"action": "upgrade", "from_version": CURRENT_VERSION, "ok": ok,
                             "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            return {"success": ok, "from": CURRENT_VERSION, "output": result.stdout[-500:]}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def rollback(self, target_version: str) -> dict[str, Any]:
        """Rollback to a specific version."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", f"nous-runtime=={target_version}"],
                capture_output=True, text=True, timeout=120,
            )
            ok = result.returncode == 0
            self._save_state({"action": "rollback", "to_version": target_version, "ok": ok,
                             "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            return {"success": ok, "target": target_version}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _save_state(self, entry: dict) -> None:
        self._workspace.mkdir(parents=True, exist_ok=True)
        history = []
        if self._state_file.exists():
            history = json.loads(self._state_file.read_text())
        history.append(entry)
        self._state_file.write_text(json.dumps(history[-20:], indent=2))

    def get_history(self) -> list[dict]:
        if self._state_file.exists():
            return json.loads(self._state_file.read_text())
        return []
