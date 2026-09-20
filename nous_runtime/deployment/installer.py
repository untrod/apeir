# -*- coding: utf-8 -*-
"""Deployment Installer — one-command installation."""
from __future__ import annotations
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from nous_runtime.deployment.platform_detect import detect_platform

_log = logging.getLogger("nous.deployment.installer")

class DeploymentInstaller:
    """Orchestrates Nous Runtime installation."""
    def __init__(self, target_dir: str = ""):
        self._target = Path(target_dir or Path.home() / ".nous")
        self._platform = detect_platform()

    def check_prerequisites(self) -> dict[str, Any]:
        issues = []
        if sys.version_info < (3, 10):
            issues.append("Python 3.10+ required")
        pip_ok = True
        try:
            subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, timeout=10, check=True)
        except Exception:
            pip_ok = False
            issues.append("pip not available")
        return {"ready": len(issues) == 0, "platform": self._platform.to_dict(), "issues": issues, "pip_ok": pip_ok}

    def install_dependencies(self) -> bool:
        deps = ["typer", "pyyaml"]
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", *deps], check=True, timeout=120)
            return True
        except Exception as exc:
            _log.error("Dependency install failed: %s", exc)
            return False

    def initialize_workspace(self) -> bool:
        try:
            self._target.mkdir(parents=True, exist_ok=True)
            (self._target / "data").mkdir(exist_ok=True)
            return True
        except Exception as exc:
            _log.error("Workspace init failed: %s", exc)
            return False

    def install(self) -> dict[str, Any]:
        report = {"success": True, "steps": []}
        steps = [
            ("check", self.check_prerequisites),
            ("deps", self.install_dependencies),
            ("workspace", self.initialize_workspace),
        ]
        for name, fn in steps:
            try:
                result = fn()
                report["steps"].append({"step": name, "ok": True, "result": result if isinstance(result, dict) else None})
            except Exception as exc:
                report["steps"].append({"step": name, "ok": False, "error": str(exc)})
                report["success"] = False
        return report
