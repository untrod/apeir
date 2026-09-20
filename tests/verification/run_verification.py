#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nous Runtime — Comprehensive Verification Runner.

Runs:
  1. Static checks (imports, bypass audit, registry consistency)
  2. All new module tests
  3. All existing regression tests
  4. Coverage collection
  5. JUnit XML output

Usage:
    python tests/verification/run_verification.py [--junit] [--coverage] [--quick]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run_step(name: str, args: list[str], timeout: int = 300) -> tuple[bool, str, float]:
    """Run a command and return (passed, output, duration_seconds)."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    start = time.monotonic()
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        duration = time.monotonic() - start
        passed = result.returncode == 0
        output = result.stdout + "\n" + result.stderr
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} ({duration:.1f}s)")
        if not passed:
            # Print last 30 lines of output
            lines = output.strip().split("\n")
            for line in lines[-30:]:
                print(f"  | {line}")
        return passed, output, duration
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        print(f"  ❌ TIMEOUT (>{timeout}s)")
        return False, f"Timeout after {timeout}s", duration
    except Exception as e:
        duration = time.monotonic() - start
        print(f"  ❌ ERROR: {e}")
        return False, str(e), duration


def generate_junit(results: dict[str, tuple[bool, str, float]],
                    output_path: str) -> str:
    """Generate JUnit XML from test results."""
    testsuite = ET.Element("testsuite", {
        "name": "Nous Runtime Verification",
        "tests": str(len(results)),
        "failures": str(sum(1 for p, _, _ in results.values() if not p)),
        "errors": "0",
        "time": f"{sum(d for _, _, d in results.values()):.2f}",
    })

    for name, (passed, output, duration) in results.items():
        testcase = ET.SubElement(testsuite, "testcase", {
            "classname": "verification",
            "name": name,
            "time": f"{duration:.2f}",
        })
        if not passed:
            failure = ET.SubElement(testcase, "failure", {
                "message": f"{name} failed",
            })
            failure.text = output[-2000:]  # Last 2000 chars

    tree = ET.ElementTree(testsuite)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path


def collect_coverage_report() -> dict:
    """Parse .coverage or coverage.json if available."""
    coverage_file = PROJECT_ROOT / "coverage.json"
    if coverage_file.exists():
        with open(coverage_file) as f:
            return json.load(f)
    return {"note": "Run with --coverage and pytest-cov installed"}


def main():
    parser = argparse.ArgumentParser(description="Nous Runtime Verification Runner")
    parser.add_argument("--junit", action="store_true", help="Generate JUnit XML")
    parser.add_argument("--coverage", action="store_true", help="Collect coverage")
    parser.add_argument("--quick", action="store_true", help="Skip slow tests")
    args = parser.parse_args()

    results: dict[str, tuple[bool, str, float]] = {}
    total_start = time.monotonic()

    # Step 1: Static checks
    passed, output, dur = run_step(
        "Static Checks (imports, bypass audit, registry, error codes, state machines)",
        [sys.executable, "-m", "pytest", "tests/verification/test_static_checks.py",
         "-v", "--tb=short"],
    )
    results["static_checks"] = (passed, output, dur)

    # Step 2: New object model tests
    passed, output, dur = run_step(
        "Object Model v2 Tests",
        [sys.executable, "-m", "pytest", "tests/test_kernel/test_object_model_v2.py",
         "-v", "--tb=short"],
    )
    results["object_model_v2"] = (passed, output, dur)

    # Step 3: Kernel exports tests
    passed, output, dur = run_step(
        "Kernel Exports Tests",
        [sys.executable, "-m", "pytest", "tests/test_kernel/test_kernel_exports.py",
         "-v", "--tb=short"],
    )
    results["kernel_exports"] = (passed, output, dur)

    # Step 4: Batch 1 server tests
    passed, output, dur = run_step(
        "Batch 1 Server Tests (config, checkpoint, server, recovery)",
        [sys.executable, "-m", "pytest", "tests/test_kernel/test_batch1_server.py",
         "-v", "--tb=short"],
    )
    results["batch1_server"] = (passed, output, dur)

    # Step 5: Full integration tests
    passed, output, dur = run_step(
        "Full Integration Tests (e2e chain, admission, vault, sandbox, scheduler)",
        [sys.executable, "-m", "pytest", "tests/test_kernel/test_full_integration.py",
         "-v", "--tb=short"],
    )
    results["full_integration"] = (passed, output, dur)

    if not args.quick:
        # Step 6: Existing regression tests
        passed, output, dur = run_step(
            "Architecture Tests (import boundaries, state ownership)",
            [sys.executable, "-m", "pytest", "tests/test_architecture/",
             "-v", "--tb=short", "--timeout=60"],
            timeout=120,
        )
        results["architecture"] = (passed, output, dur)

        passed, output, dur = run_step(
            "Governance Tests (security, gates, API)",
            [sys.executable, "-m", "pytest", "tests/governance/",
             "-v", "--tb=short", "--timeout=60"],
            timeout=120,
        )
        results["governance"] = (passed, output, dur)

        passed, output, dur = run_step(
            "Provider Tests",
            [sys.executable, "-m", "pytest", "tests/test_provider/",
             "-v", "--tb=short", "--timeout=60"],
            timeout=120,
        )
        results["provider"] = (passed, output, dur)

        passed, output, dur = run_step(
            "Planner Tests",
            [sys.executable, "-m", "pytest", "tests/test_planner/",
             "-v", "--tb=short", "--timeout=60"],
            timeout=120,
        )
        results["planner"] = (passed, output, dur)

        # Step 7: Coverage
        if args.coverage:
            coverage_args = [
                sys.executable, "-m", "pytest",
                "tests/test_kernel/",
                "tests/verification/",
                "--cov=nous_runtime.kernel",
                "--cov=nous_runtime.security",
                "--cov=nous_runtime.capability",
                "--cov=nous_runtime.intelligence",
                "--cov=nous_runtime.connectivity",
                "--cov=nous_runtime.context",
                "--cov=nous_runtime.device",
                "--cov=nous_runtime.provider",
                "--cov=nous_runtime.agent",
                "--cov=nous_runtime.project",
                "--cov-report=term",
                "--cov-report=json",
                "--cov-report=html:htmlcov",
                "-v",
            ]
            passed, output, dur = run_step(
                "Coverage Report",
                coverage_args,
                timeout=300,
            )
            results["coverage"] = (passed, output, dur)

    # Summary
    total_dur = time.monotonic() - total_start
    passed_count = sum(1 for p, _, _ in results.values() if p)
    failed_count = sum(1 for p, _, _ in results.values() if not p)

    print(f"\n{'='*60}")
    print("  VERIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Total: {len(results)} suites, {passed_count} passed, {failed_count} failed")
    print(f"  Duration: {total_dur:.1f}s")
    print()

    for name, (passed, _, dur) in results.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {name} ({dur:.1f}s)")

    # JUnit
    if args.junit:
        junit_path = str(PROJECT_ROOT / "verification_results.xml")
        generate_junit(results, junit_path)
        print(f"\n  JUnit XML: {junit_path}")

    # Coverage
    if args.coverage:
        collect_coverage_report()
        cov_path = str(PROJECT_ROOT / "coverage.json")
        print(f"  Coverage JSON: {cov_path}")

    # Exit
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
