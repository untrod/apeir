#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated RC1 evidence collection.

Orchestrates all automated checks and writes results to .audit/results/.
Updates EVIDENCE_INDEX.json with status and file references.

Usage:
    python scripts/collect_audit_evidence.py              # all categories
    python scripts/collect_audit_evidence.py --category tests
    python scripts/collect_audit_evidence.py --status     # print gate status
    python scripts/collect_audit_evidence.py --json       # machine-readable
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / ".audit"
RESULTS_DIR = AUDIT_DIR / "results"
EVIDENCE_INDEX_PATH = AUDIT_DIR / "EVIDENCE_INDEX.json"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)



# Helpers


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run a command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def _write_result(filename: str, data: dict) -> Path:
    path = RESULTS_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _update_gate(gate_id: str, status: str, evidence_paths: list[str]) -> None:
    if not EVIDENCE_INDEX_PATH.exists():
        return
    index = json.loads(EVIDENCE_INDEX_PATH.read_text(encoding="utf-8"))
    if gate_id in index.get("gates", {}):
        index["gates"][gate_id]["status"] = status
        for p in evidence_paths:
            if p not in index["gates"][gate_id]["evidence"]:
                index["gates"][gate_id]["evidence"].append(p)
    index["generated_at"] = _ts()
    EVIDENCE_INDEX_PATH.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )



# Collectors


def collect_tests() -> tuple[str, list[str]]:
    """Run full test suite and collect results."""
    ts = _ts()
    xml_path = RESULTS_DIR / f"pytest-{ts}.xml"

    code, stdout, stderr = _run([
        sys.executable, "-m", "pytest", "tests/", "-q",
        f"--junitxml={xml_path}",
    ], timeout=600)

    result = {
        "category": "tests",
        "timestamp": ts,
        "exit_code": code,
        "stdout_summary": stdout.split("\n")[-5:] if stdout else [],
        "stderr_tail": stderr.split("\n")[-10:] if stderr else [],
        "artifacts": [str(xml_path)],
    }
    _write_result(f"test-suite-{ts}.json", result)

    status = "pass" if code == 0 else "fail"
    evidence = [f"results/pytest-{ts}.xml", f"results/test-suite-{ts}.json"]
    _update_gate("gate_3_test_suite", status, evidence)

    return status, evidence


def collect_smoke_test() -> tuple[str, list[str]]:
    """Run smoke test."""
    ts = _ts()
    code, stdout, stderr = _run([
        sys.executable, "tools/smoke_test.py", "--json",
    ], timeout=120)

    result = {
        "category": "smoke_test",
        "timestamp": ts,
        "exit_code": code,
        "stdout": stdout[:5000],
        "stderr": stderr[:2000],
    }
    _write_result(f"smoke-test-{ts}.json", result)
    status = "pass" if code == 0 else "fail"
    evidence = [f"results/smoke-test-{ts}.json"]
    return status, evidence


def collect_security_scan() -> tuple[str, list[str]]:
    """Run security scan."""
    ts = _ts()
    code, stdout, stderr = _run([
        sys.executable, "scripts/security_scan.py", "--json",
    ], timeout=120)

    result = {
        "category": "security_scan",
        "timestamp": ts,
        "exit_code": code,
        "stdout": stdout[:5000],
        "stderr": stderr[:2000],
    }
    _write_result(f"security-scan-{ts}.json", result)
    status = "pass" if code == 0 else "fail"
    evidence = [f"results/security-scan-{ts}.json"]
    _update_gate("gate_4_security_scan", status, evidence)
    return status, evidence


def collect_version_check() -> tuple[str, list[str]]:
    """Run version and schema consistency tests."""
    ts = _ts()
    code, stdout, stderr = _run([
        sys.executable, "-m", "pytest",
        "tests/test_version_consistency.py",
        "tests/test_schema_consistency.py",
        "-v", "-q",
    ], timeout=120)

    result = {
        "category": "version_check",
        "timestamp": ts,
        "exit_code": code,
        "stdout": stdout[:3000],
        "stderr": stderr[:1000],
    }
    _write_result(f"version-check-{ts}.json", result)
    status = "pass" if code == 0 else "fail"
    evidence = [f"results/version-check-{ts}.json"]
    _update_gate("gate_1_code_freeze", status, evidence)
    return status, evidence


def collect_workflow_validation() -> tuple[str, list[str]]:
    """Run workflow validation."""
    ts = _ts()
    code, stdout, stderr = _run([
        sys.executable, "tools/workflow_validation.py", "--json",
    ], timeout=180)

    result = {
        "category": "workflow_validation",
        "timestamp": ts,
        "exit_code": code,
        "stdout": stdout[:5000],
    }
    _write_result(f"workflow-validation-{ts}.json", result)
    status = "pass" if code == 0 else "fail"
    evidence = [f"results/workflow-validation-{ts}.json"]
    return status, evidence



# Main


COLLECTORS = {
    "version": ("Version consistency check", collect_version_check),
    "tests": ("Full test suite", collect_tests),
    "smoke": ("Smoke test", collect_smoke_test),
    "security": ("Security scan", collect_security_scan),
    "workflow": ("Workflow validation", collect_workflow_validation),
}


def cmd_collect(category: str | None = None) -> int:
    """Run evidence collection."""
    categories = [category] if category else list(COLLECTORS.keys())
    results: dict[str, tuple[str, list[str]]] = {}

    for cat in categories:
        if cat not in COLLECTORS:
            print(f"Unknown category: {cat}")
            print(f"Available: {', '.join(COLLECTORS.keys())}")
            return 1

    for cat in categories:
        label, fn = COLLECTORS[cat]
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        status, evidence = fn()
        results[cat] = (status, evidence)
        icon = "PASS" if status == "pass" else "FAIL"
        print(f"  Result: {icon}")
        for e in evidence:
            print(f"    → {e}")

    # Summary
    print(f"\n{'='*60}")
    print("  Summary")
    print(f"{'='*60}")
    passed = sum(1 for s, _ in results.values() if s == "pass")
    failed = len(results) - passed
    for cat, (status, _) in results.items():
        icon = "PASS" if status == "pass" else "FAIL"
        print(f"  {icon} {cat}: {status}")
    print(f"\n  {passed}/{len(results)} passed, {failed} failed")

    return 0 if failed == 0 else 1


def cmd_status() -> int:
    """Print current gate status from EVIDENCE_INDEX.json."""
    if not EVIDENCE_INDEX_PATH.exists():
        print("EVIDENCE_INDEX.json not found. Run collection first.")
        return 1

    index = json.loads(EVIDENCE_INDEX_PATH.read_text(encoding="utf-8"))
    gates = index.get("gates", {})

    print(f"\nRC1 Release Gate Status (v{index.get('version', '?')})")
    print(f"Last updated: {index.get('generated_at', 'never')}\n")
    print(f"{'#':<5} {'Gate':<35} {'Status':<15} {'Evidence':<10}")
    print("-" * 65)

    status_order = {"pass": 0, "in_progress": 1, "partial": 2, "pending": 3, "fail": 4}
    sorted_gates = sorted(gates.items(), key=lambda x: status_order.get(x[1]["status"], 99))

    for gate_id, gate in sorted_gates:
        gate_num = gate_id.split("_")[1]
        icon = {"pass": "PASS", "in_progress": "🔄", "partial": "WARN",
                "pending": "⏳", "fail": "FAIL"}.get(gate["status"], "❓")
        evidence_count = len(gate.get("evidence", []))
        print(f"{gate_num:<5} {gate['description'][:33]:<35} {icon} {gate['status']:<10} {evidence_count} files")

    total = len(gates)
    passed = sum(1 for g in gates.values() if g["status"] == "pass")
    failed = sum(1 for g in gates.values() if g["status"] == "fail")
    print(f"\n{passed}/{total} passed, {failed} failed, {total - passed - failed} pending")
    return 0


def main():
    if "--status" in sys.argv:
        sys.exit(cmd_status())
    elif "--json" in sys.argv:
        # Machine-readable: just print the EVIDENCE_INDEX
        if EVIDENCE_INDEX_PATH.exists():
            print(EVIDENCE_INDEX_PATH.read_text(encoding="utf-8"))
        sys.exit(0)

    category = None
    for arg in sys.argv[1:]:
        if arg.startswith("--category="):
            category = arg.split("=", 1)[1]
        elif arg == "--category" and len(sys.argv) > sys.argv.index(arg) + 1:
            category = sys.argv[sys.argv.index(arg) + 1]

    sys.exit(cmd_collect(category))


if __name__ == "__main__":
    main()
