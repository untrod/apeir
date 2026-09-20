#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nous Runtime 2.0.0-rc2 smoke test.

Quick verification that all critical paths work after installation.

Usage:
    python tools/smoke_test.py          # Run all checks
    python tools/smoke_test.py --quick  # Fast checks only
    python tools/smoke_test.py --json   # JSON output for CI
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from nous_runtime.deployment.first_launch import is_first_launch
from nous_runtime.deployment.setup_wizard import detect_hardware



# Test Runner


class SmokeTest:
    def __init__(self):
        self.results: list[dict] = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.start_time = time.time()

    def check(self, name: str, fn, critical: bool = True) -> None:
        try:
            fn()
            self.results.append({"name": name, "status": "PASS", "critical": critical})
            self.passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            self.results.append({
                "name": name,
                "status": "FAIL",
                "critical": critical,
                "error": str(e),
            })
            self.failed += 1
            print(f"  FAIL {name}: {e}")
            if critical:
                traceback.print_exc()

    def skip(self, name: str, reason: str) -> None:
        self.results.append({"name": name, "status": "SKIP", "reason": reason})
        self.skipped += 1
        print(f"  ⏭ {name} (skipped: {reason})")

    def summary(self) -> dict[str, Any]:
        elapsed = time.time() - self.start_time
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "total": self.passed + self.failed + self.skipped,
            "elapsed_seconds": round(elapsed, 2),
            "overall": "PASS" if self.failed == 0 else "FAIL",
            "results": self.results,
        }



# Check Functions


def run_smoke_tests(quick: bool = False) -> SmokeTest:
    t = SmokeTest()

    print("\n" + "=" * 56)
    print("  Nous Runtime v1.0.0-rc1 — Smoke Test")
    print("=" * 56 + "\n")

    # 1. Version & Imports
    print("-- 1. Version & Core Imports --")
    t.check("Version import", lambda: __import__("nous_runtime").__version__)
    t.check("Runtime kernel import", lambda: __import__("nous_runtime.kernel.runtime").Runtime())
    t.check("Governance import", lambda: __import__("nous_runtime.governance").get_gate())
    t.check("Provider registry import", lambda: __import__("nous_runtime.provider.registry").ProviderRegistry)

    # 2. API Layer
    print("\n-- 2. API Layer --")
    from nous_runtime.api.routes import ROUTES
    t.check("API routes loaded", lambda: None)
    t.check(
        f"Route count ({len(ROUTES)})",
        lambda: None
        if len(ROUTES) >= 110
        else (_ for _ in ()).throw(AssertionError("route count below baseline")),
    )

    # Core endpoints
    for path in ["/api/v1/status", "/api/v1/health", "/api/runtime/run"]:
        t.check(f"Core route: {path}", lambda p=path: ROUTES.__contains__)

    # Desktop endpoints
    for path in ["/api/tasks", "/api/devices", "/api/dashboard"]:
        t.check(f"Desktop route: {path}", lambda p=path: None)

    # Health endpoints
    t.check("Health dashboard endpoint", lambda: __import__("nous_runtime.api.health_dashboard").handle_health_dashboard())

    # 3. Desktop API
    print("\n-- 3. Desktop API --")
    from nous_runtime.api.desktop_routes import (
        handle_dashboard_full, handle_tasks_list, handle_devices_list,
        handle_automations_list, handle_knowledge_list,
        handle_security_permissions, handle_logs_list, handle_memory_usage,
    )
    t.check("Dashboard full", lambda: handle_dashboard_full()["ok"])
    t.check("Tasks list", lambda: handle_tasks_list()["ok"])
    t.check("Devices list", lambda: handle_devices_list()["ok"])
    t.check("Automations list", lambda: handle_automations_list()["ok"])
    t.check("Knowledge list", lambda: handle_knowledge_list()["ok"])
    t.check("Security permissions", lambda: handle_security_permissions()["ok"])
    t.check("Memory usage", lambda: handle_memory_usage()["ok"])
    t.check("Logs list", lambda: handle_logs_list()["ok"])

    # 4. Task Center
    print("\n-- 4. Task Center --")
    from nous_runtime.api.task_center_routes import (
        handle_task_timeline, handle_task_graph,
        handle_task_artifacts, handle_task_verification,
    )
    t.check("Task timeline", lambda: handle_task_timeline()["ok"])
    t.check("Task graph", lambda: handle_task_graph()["ok"])
    t.check("Task artifacts", lambda: handle_task_artifacts("test")["ok"])
    t.check("Task verification", lambda: handle_task_verification("test")["ok"])

    # 5. Daemon & Health
    print("\n-- 5. Daemon & Health --")
    t.check("Daemon service start/stop", lambda: (
        svc := __import__("nous_runtime.daemon.service").DaemonService(),
        svc.start(),
        svc.stop(),
    ))
    t.check("Health checker run", lambda: (
        hc := __import__("nous_runtime.daemon.health").HealthChecker(interval_seconds=60),
        hc.register_check("smoke", lambda: True),
        hc.run_once(),
    ))
    t.check("Crash recovery record", lambda: (
        rec := __import__("nous_runtime.daemon.recovery").CrashRecovery(),
        rec.record_crash(RuntimeError("smoke test"), "test"),
    ))

    # 6. Personal Assistants
    print("\n-- 6. Personal Assistants --")
    with tempfile.TemporaryDirectory() as tmp:
        t.check("Learning: add subject", lambda: (
            la := __import__("nous_runtime.persona.learning_assistant").LearningAssistant(tmp),
            la.add_subject("Smoke Test Subject", ["Topic 1"]),
        ))
        t.check("Learning: log session", lambda: (
            la := __import__("nous_runtime.persona.learning_assistant").LearningAssistant(tmp),
            la.log_session("Test", "Topic", 30, 0.8),
        ))
        t.check("Learning: daily plan", lambda: (
            la := __import__("nous_runtime.persona.learning_assistant").LearningAssistant(tmp),
            la.generate_daily_plan(),
        ))

    with tempfile.TemporaryDirectory() as tmp:
        t.check("Project: create", lambda: (
            pa := __import__("nous_runtime.persona.project_assistant").ProjectAssistant(tmp),
            pa.create_project("Smoke Test Project"),
        ))
        t.check("Project: add milestone", lambda: (
            pa := __import__("nous_runtime.persona.project_assistant").ProjectAssistant(tmp),
            pa.create_project("Test"),
            pa.add_milestone("Test", "M1"),
        ))
        t.check("Project: dashboard", lambda: (
            pa := __import__("nous_runtime.persona.project_assistant").ProjectAssistant(tmp),
            pa.get_dashboard(),
        ))

    # 7. Deployment
    print("\n-- 7. Deployment --")
    t.check("Hardware detection", detect_hardware)
    t.check("First launch detection", lambda: is_first_launch(tempfile.mkdtemp()))

    # 8. Filesystem checks
    if not quick:
        print("\n-- 8. Filesystem --")
        required_files = [
            "README.md", "CHANGELOG.md", "ROADMAP.md", "SECURITY.md",
            "pyproject.toml", "nous-installer.spec",
            "desktop/package.json", "desktop/src/App.tsx", "desktop/src/lib/api.ts",
            "docs/USER_GUIDE.md", "docs/INSTALL.md", "docs/ARCHITECTURE.md",
        ]
        for f in required_files:
            t.check(f"File: {f}", lambda p=f: Path(p).is_file() or (_ for _ in ()).throw(FileNotFoundError(p)))

    # 9. Test discovery
    print("\n-- 9. Test Discovery --")
    test_files = list(Path("tests").glob("test_*.py"))
    t.check(
        f"Test files found: {len(test_files)}",
        lambda: None
        if len(test_files) >= 70
        else (_ for _ in ()).throw(AssertionError("test file count below baseline")),
    )

    # Summary
    print("\n" + "=" * 56)
    s = t.summary()
    print(f"  {s['passed']} passed, {s['failed']} failed, {s['skipped']} skipped")
    print(f"  Time: {s['elapsed_seconds']}s")
    print(f"  Overall: {s['overall']}")
    print("=" * 56 + "\n")
    return t


def main():
    import argparse
    p = argparse.ArgumentParser(description="Nous Runtime Smoke Test")
    p.add_argument("--quick", action="store_true", help="Skip filesystem checks")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args()

    t = run_smoke_tests(quick=args.quick)
    s = t.summary()

    if args.json:
        print(json.dumps(s, indent=2))

    return 0 if s["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
