#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nous Runtime 2.0.0-rc2 release execution script.

One command to execute the entire release pipeline:

    python tools/release_exec.py

Stages:
  1. Pre-flight checks (Python, deps, file integrity)
  2. Test suite (pytest)
  3. RC validation
  4. Smoke test
  5. Workflow validation
  6. Stability quick check
  7. Build installer (pyinstaller)
  8. Build report generation
  9. Release artifact manifest

Output:
    docs/release/RELEASE_EXECUTION_REPORT.md
    dist/ (installer artifacts)
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from nous_runtime.version import __version__



# Framework


class Stage:
    def __init__(self, name: str, command: str = "", fn=None):
        self.name = name
        self.command = command
        self.fn = fn
        self.status = "pending"
        self.output = ""
        self.error = ""
        self.elapsed = 0.0
        self.artifacts: list[str] = []


class ReleaseExecutor:
    def __init__(self):
        self.stages: list[Stage] = []
        self.start_time = time.time()
        self.workspace = Path.cwd()

    def add_stage(self, name: str, command: str = "", fn=None) -> Stage:
        s = Stage(name, command, fn)
        self.stages.append(s)
        return s

    def run_stage(self, stage: Stage) -> bool:
        print(f"\n{'='*60}")
        print(f"  {stage.name}")
        if stage.command:
            print(f"  $ {stage.command}")
        print(f"{'='*60}")

        start = time.time()
        try:
            if stage.fn:
                result = stage.fn()
                stage.output = str(result) if result else ""
                stage.status = "ok"
            elif stage.command:
                argv = shlex.split(stage.command, posix=sys.platform != "win32")
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=str(self.workspace),
                )
                stage.output = proc.stdout[-3000:] if len(proc.stdout) > 3000 else proc.stdout
                stage.error = proc.stderr[-1000:] if proc.stderr else ""
                stage.status = "ok" if proc.returncode == 0 else "fail"
            else:
                stage.status = "ok"
        except subprocess.TimeoutExpired:
            stage.status = "fail"
            stage.error = "Timeout (>600s)"
        except Exception as e:
            stage.status = "fail"
            stage.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()

        stage.elapsed = time.time() - start
        icon = "PASS" if stage.status == "ok" else "FAIL"
        print(f"  {icon} {stage.status.upper()} ({stage.elapsed:.1f}s)")
        if stage.error:
            print(f"  Error: {stage.error[:500]}")
        return stage.status == "ok"

    def report(self) -> dict:
        elapsed = time.time() - self.start_time
        passed = sum(1 for s in self.stages if s.status == "ok")
        failed = sum(1 for s in self.stages if s.status == "fail")
        return {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "platform": sys.platform,
            "python": sys.version,
            "elapsed_seconds": round(elapsed, 1),
            "stages_total": len(self.stages),
            "stages_passed": passed,
            "stages_failed": failed,
            "overall": "PASS" if failed == 0 else "FAIL",
            "stages": [
                {
                    "name": s.name,
                    "status": s.status,
                    "elapsed": s.elapsed,
                    "artifacts": s.artifacts,
                }
                for s in self.stages
            ],
        }



# Stage Functions


def check_python() -> str:
    v = sys.version_info
    if v < (3, 10):
        raise SystemExit(f"Python 3.10+ required, got {v.major}.{v.minor}")
    return f"Python {sys.version}"


def check_deps() -> str:
    missing = []
    for mod in ["typer", "yaml", "jsonschema"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise SystemExit(f"Missing dependencies: {', '.join(missing)}")
    return "Core deps OK"


def check_integrity() -> str:
    frozen = [
        "nous_runtime/kernel", "nous_runtime/intelligence",
        "nous_runtime/provider", "nous_runtime/task",
        "nous_runtime/governance", "nous_runtime/capability",
        "nous_runtime/planner", "nous_runtime/retrieval",
        "nous_runtime/execution",
    ]
    for d in frozen:
        if not Path(d).is_dir():
            raise SystemExit(f"Frozen directory missing: {d}")
    return f"{len(frozen)} frozen dirs intact"


def check_imports() -> str:
    modules = [
        "nous_runtime", "nous_runtime.kernel.runtime",
        "nous_runtime.intelligence.engine", "nous_runtime.provider.registry",
        "nous_runtime.governance", "nous_runtime.api.routes",
        "nous_runtime.api.desktop_routes", "nous_runtime.api.task_center_routes",
        "nous_runtime.api.health_dashboard",
        "nous_runtime.deployment.setup_wizard", "nous_runtime.deployment.first_launch",
        "nous_runtime.daemon.health", "nous_runtime.daemon.recovery",
        "nous_runtime.persona.learning_assistant", "nous_runtime.persona.project_assistant",
        "nous_runtime.cli.main",
    ]
    for mod in modules:
        __import__(mod)
    return f"{len(modules)} modules OK"


def count_tests() -> str:
    test_files = list(Path("tests").glob("test_*.py"))
    return f"{len(test_files)} test files"


def check_docs() -> str:
    required = [
        "README.md", "CHANGELOG.md", "ROADMAP.md", "SECURITY.md",
        "docs/USER_GUIDE.md", "docs/INSTALL.md", "docs/ARCHITECTURE.md",
        "docs/release/PUBLIC_RELEASE_CHECKLIST.md",
        "docs/release/KNOWN_LIMITATIONS.md",
    ]
    missing = [f for f in required if not Path(f).is_file()]
    if missing:
        raise SystemExit(f"Missing docs: {missing}")
    return f"{len(required)} docs present"


def generate_artifact_manifest() -> str:
    """Generate manifest of all release files with checksums."""
    manifest = {"version": __version__, "files": []}

    # Add Python source
    for py_file in sorted(Path("nous_runtime").rglob("*.py")):
        rel = str(py_file).replace("\\", "/")
        try:
            sha = hashlib.sha256(py_file.read_bytes()).hexdigest()[:16]
        except Exception:
            sha = "error"
        manifest["files"].append({"path": rel, "sha256_short": sha, "category": "source"})

    # Add test files
    for test_file in sorted(Path("tests").glob("test_*.py")):
        rel = str(test_file).replace("\\", "/")
        try:
            sha = hashlib.sha256(test_file.read_bytes()).hexdigest()[:16]
        except Exception:
            sha = "error"
        manifest["files"].append({"path": rel, "sha256_short": sha, "category": "test"})

    # Save manifest
    out = Path("docs/release/RELEASE_MANIFEST.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return f"Manifest: {len(manifest['files'])} files → {out}"



# Main


def main():
    print("\n" + "=" * 60)
    print("  Nous Runtime V1.0.0 — Release Execution")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    ex = ReleaseExecutor()

    # Stage 1: Pre-flight (pure Python)
    ex.add_stage("1.1 Python version check", fn=check_python)
    ex.add_stage("1.2 Dependency check", fn=check_deps)
    ex.add_stage("1.3 Frozen directory integrity", fn=check_integrity)
    ex.add_stage("1.4 Module imports", fn=check_imports)
    ex.add_stage("1.5 Test file count", fn=count_tests)
    ex.add_stage("1.6 Documentation check", fn=check_docs)

    # Stage 2: Test Suite (requires pytest)
    ex.add_stage("2.1 Full test suite", command="python -m pytest tests/ -q --tb=short")
    ex.add_stage("2.2 RC validation", command="python -m pytest tests/test_rc_validation.py -v --tb=short --no-header -q")

    # Stage 3: Tools
    ex.add_stage("3.1 Smoke test", command="python tools/smoke_test.py --quick --json")
    ex.add_stage("3.2 Workflow validation", command="python tools/workflow_validation.py --json")

    # Stage 4: Stability
    ex.add_stage("4.1 Stability quick check", command="python tools/stability_harness.py --quick")

    # Stage 5: Build Installer
    ex.add_stage("5.1 PyInstaller check", fn=lambda: (
        __import__("PyInstaller") and "PyInstaller available"
        if __import__("importlib.util").util.find_spec("PyInstaller")
        else "PyInstaller NOT installed — run: pip install pyinstaller"
    ))
    ex.add_stage("5.2 Build NousInstaller", command="pyinstaller --noconfirm nous-installer.spec")

    # Stage 6: Artifacts
    ex.add_stage("6.1 Generate release manifest", fn=generate_artifact_manifest)

    # Execute all
    for stage in ex.stages:
        ex.run_stage(stage)
        if stage.status == "fail" and "pytest" in stage.name:
            print("  WARN Test failures detected. Review output above.")
        if stage.status == "fail" and "pyinstaller" in stage.name.lower():
            print("  WARN Installer build failed. Check that pyinstaller is installed.")

    # Report
    report = ex.report()

    print(f"\n{'='*60}")
    print("  RELEASE EXECUTION SUMMARY")
    print(f"{'='*60}")
    for s in ex.stages:
        icon = "PASS" if s.status == "ok" else "FAIL"
        print(f"  {icon} {s.name} ({s.elapsed:.1f}s)")
    print(f"\n  Passed: {report['stages_passed']}/{report['stages_total']}")
    print(f"  Overall: {report['overall']}")
    print(f"  Time: {report['elapsed_seconds']:.1f}s")
    print(f"{'='*60}\n")

    # Write report
    out = Path("docs/release/RELEASE_EXECUTION_REPORT.md")
    out.parent.mkdir(parents=True, exist_ok=True)

    md = f"""# Nous Runtime V1.0.0 — Release Execution Report

> **Generated:** {report['timestamp']}
> **Platform:** {report['platform']}
> **Python:** {report['python'].split()[0]}
> **Overall:** {report['overall']}
> **Duration:** {report['elapsed_seconds']:.1f}s

## Stage Results

| # | Stage | Status | Time |
|---|-------|--------|------|
"""
    for i, s in enumerate(ex.stages):
        icon = "PASS" if s.status == "ok" else "FAIL"
        md += f"| {i+1} | {s.name} | {icon} {s.status} | {s.elapsed:.1f}s |\n"

    md += f"""
## Summary

- **Stages Passed:** {report['stages_passed']}/{report['stages_total']}
- **Stages Failed:** {report['stages_failed']}/{report['stages_total']}
- **Overall:** {report['overall']}

## Failed Stages

"""
    failed = [s for s in ex.stages if s.status == "fail"]
    if failed:
        for s in failed:
            md += f"### {s.name}\n```\n{s.error[:1000] if s.error else s.output[-1000:]}\n```\n\n"
    else:
        md += "No failures. 🎉\n\n"

    md += """## Release Commands

```bash
# Tag release
git tag -a v1.0.0 -m "Nous Runtime v1.0.0 — Personal AI Operating Runtime"
git push origin v1.0.0

# Build desktop app (requires Node.js + Rust)
cd desktop && npm install && npm run tauri build
# → src-tauri/target/release/bundle/

# Create GitHub Release
# 1. Go to: https://github.com/<repo>/releases/new
# 2. Tag: v1.0.0
# 3. Attach: dist/NousInstaller.exe
# 4. Attach: desktop bundles
```

## Artifact Locations

| Artifact | Path |
|----------|------|
| Python Installer | `dist/NousInstaller.exe` |
| Desktop App | `desktop/src-tauri/target/release/bundle/` |
| Release Manifest | `docs/release/RELEASE_MANIFEST.json` |
| This Report | `docs/release/RELEASE_EXECUTION_REPORT.md` |
"""
    out.write_text(md, encoding="utf-8")
    print(f"  📄 Report: {out}")

    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
