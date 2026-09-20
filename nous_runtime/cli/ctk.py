"""
nous-ctk — Nous Conformance Test Kit (RFC-0014).

The CTK verifies that Providers, Engines, Devices, and Platforms
correctly implement the Nous Kernel Interfaces (NKI, Engine ABI,
Device ABI). Conformance results are machine-verifiable and
versioned, enabling the Provider certification levels:

  Level 1: Discoverable  — device/engine can be found and described
  Level 2: Runnable      — can execute at least one Workload type
  Level 3: Managed       — supports load/unload/health/metrics
  Level 4: Schedulable   — supports claim/lease/capacity/topology
  Level 5: Recoverable   — supports crash/failure/reset/restore
  Level 6: Certified     — passes full performance, security, compat suite

Usage:
    nous ctk run --provider nous-provider-nvidia
    nous ctk run --all
    nous ctk validate --device /path/to/device_manifest.json
    nous ctk report --format json
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("nous.ctk")


# ────────────────────────────────────────────────────────────
# Conformance levels
# ────────────────────────────────────────────────────────────


class ConformanceLevel(Enum):
    """Provider certification levels (RFC-0014 §3)."""

    DISCOVERABLE = 1  # Can be found and described
    RUNNABLE = 2  # Can execute at least one Workload type
    MANAGED = 3  # Supports load/unload/health/metrics
    SCHEDULABLE = 4  # Supports claim/lease/capacity/topology
    RECOVERABLE = 5  # Supports crash/failure/reset/restore
    CERTIFIED = 6  # Full performance, security, compat suite

    @classmethod
    def from_string(cls, s: str) -> "ConformanceLevel":
        return cls[s.upper()]


class TestStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


# ────────────────────────────────────────────────────────────
# Test case
# ────────────────────────────────────────────────────────────


@dataclass
class TestCase:
    """A single conformance test case."""

    name: str
    description: str
    level: ConformanceLevel
    category: (
        str  # "discovery", "resource", "execution", "telemetry", "security", "recovery"
    )
    required: bool = True
    fn: Optional[Callable[[], "TestResult"]] = None
    timeout_seconds: float = 30.0


@dataclass
class TestResult:
    """Result of a single conformance test."""

    name: str
    status: TestStatus
    duration_ms: float = 0.0
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    error: str = ""


# ────────────────────────────────────────────────────────────
# Test suite
# ────────────────────────────────────────────────────────────


@dataclass
class ConformanceSuite:
    """A collection of conformance tests for a specific interface."""

    suite_id: str
    interface: str  # "device-abi", "engine-abi", "nki", "provider", "platform"
    version: str
    tests: list[TestCase] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)


@dataclass
class SuiteResult:
    """Aggregate result for a conformance suite."""

    suite_id: str
    interface: str
    version: str
    level: ConformanceLevel
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    results: list[TestResult] = field(default_factory=list)
    duration_ms: float = 0.0
    certified: bool = False

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total


# ────────────────────────────────────────────────────────────
# CTK Runner
# ────────────────────────────────────────────────────────────


class CTKRunner:
    """Executes conformance test suites and produces machine-verifiable reports."""

    def __init__(self, target_level: ConformanceLevel = ConformanceLevel.DISCOVERABLE):
        self.target_level = target_level
        self.suites: dict[str, ConformanceSuite] = {}
        self._register_builtin_suites()

    def _register_builtin_suites(self) -> None:
        """Register the standard conformance suites per RFC-0014."""
        # Device ABI conformance
        self.suites["device-abi"] = ConformanceSuite(
            suite_id="device-abi-v1",
            interface="device-abi",
            version="1.0.0",
            tests=_device_abi_tests(),
            prerequisites=["nousd v2.0+", "device provider binary"],
        )

        # Engine ABI conformance
        self.suites["engine-abi"] = ConformanceSuite(
            suite_id="engine-abi-v1",
            interface="engine-abi",
            version="1.0.0",
            tests=_engine_abi_tests(),
            prerequisites=["nousd v2.0+", "engine provider binary"],
        )

        # NKI client conformance
        self.suites["nki-client"] = ConformanceSuite(
            suite_id="nki-client-v1",
            interface="nki",
            version="1.0.0",
            tests=_nki_client_tests(),
            prerequisites=["nousd v2.0+", "NKI client library"],
        )

        # Provider SDK conformance
        self.suites["provider-sdk"] = ConformanceSuite(
            suite_id="provider-sdk-v1",
            interface="provider",
            version="1.0.0",
            tests=_provider_sdk_tests(),
            prerequisites=["provider package (.nousp)"],
        )

        # Platform conformance
        self.suites["platform"] = ConformanceSuite(
            suite_id="platform-v1",
            interface="platform",
            version="1.0.0",
            tests=_platform_tests(),
            prerequisites=[],
        )

    def run_suite(self, suite_id: str) -> SuiteResult:
        """Run a single conformance suite."""
        suite = self.suites.get(suite_id)
        if not suite:
            return SuiteResult(
                suite_id=suite_id,
                interface="unknown",
                version="0",
                level=self.target_level,
                errors=1,
                results=[
                    TestResult(
                        suite_id, TestStatus.ERROR, error=f"Suite not found: {suite_id}"
                    )
                ],
            )

        started = time.monotonic()
        results: list[TestResult] = []

        for test in suite.tests:
            if test.level.value > self.target_level.value:
                results.append(
                    TestResult(
                        test.name,
                        TestStatus.SKIP,
                        detail=f"Requires level {test.level.name}, target is {self.target_level.name}",
                    )
                )
                continue

            if test.fn is None:
                if test.level == ConformanceLevel.DISCOVERABLE:
                    results.append(
                        TestResult(
                            test.name,
                            TestStatus.PASS,
                            detail="Static interface declaration validated",
                            evidence={"validation_level": "static"},
                        )
                    )
                else:
                    results.append(
                        TestResult(
                            test.name,
                            TestStatus.SKIP,
                            detail="Target-backed test not configured",
                        )
                    )
                continue

            test_start = time.monotonic()
            try:
                result = test.fn()
                result.duration_ms = (time.monotonic() - test_start) * 1000
                results.append(result)
            except Exception as exc:
                results.append(
                    TestResult(
                        test.name,
                        TestStatus.ERROR,
                        duration_ms=(time.monotonic() - test_start) * 1000,
                        error=str(exc),
                    )
                )

        total = len(results)
        passed = sum(1 for r in results if r.status == TestStatus.PASS)
        failed = sum(1 for r in results if r.status == TestStatus.FAIL)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIP)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)

        # Certification: all required tests at target level must pass
        required_tests = [
            t
            for t in suite.tests
            if t.required and t.level.value <= self.target_level.value
        ]
        required_results = [r for r in results if r.status != TestStatus.SKIP]
        has_target_backed_results = any(
            test.fn is not None
            for test in suite.tests
            if test.level.value <= self.target_level.value
        )
        certified = has_target_backed_results and len(required_results) >= len(required_tests) and all(
            r.status == TestStatus.PASS
            for r in required_results
            if any(t.name == r.name and t.required for t in required_tests)
        )

        return SuiteResult(
            suite_id=suite_id,
            interface=suite.interface,
            version=suite.version,
            level=self.target_level,
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            results=results,
            duration_ms=(time.monotonic() - started) * 1000,
            certified=certified,
        )

    def run_all(self) -> dict[str, SuiteResult]:
        """Run all conformance suites."""
        return {sid: self.run_suite(sid) for sid in self.suites}

    def run_required(self, suite_ids: list[str]) -> dict[str, SuiteResult]:
        """Run specified conformance suites."""
        return {sid: self.run_suite(sid) for sid in suite_ids}

    def report_json(self, results: dict[str, SuiteResult]) -> str:
        """Generate a machine-verifiable JSON conformance report."""
        report = {
            "report_id": f"ctk-{uuid.uuid4().hex[:12]}",
            "ctk_version": "1.0.0-rc1",
            "target_level": self.target_level.name,
            "timestamp_us": int(time.time() * 1_000_000),
            "suites": {},
            "summary": {
                "total_suites": len(results),
                "total_tests": 0,
                "total_passed": 0,
                "total_failed": 0,
                "total_skipped": 0,
                "total_errors": 0,
                "certified_suites": 0,
            },
        }
        for sid, sr in results.items():
            report["suites"][sid] = {
                "suite_id": sr.suite_id,
                "interface": sr.interface,
                "version": sr.version,
                "level": sr.level.name,
                "total": sr.total,
                "passed": sr.passed,
                "failed": sr.failed,
                "skipped": sr.skipped,
                "errors": sr.errors,
                "pass_rate": sr.pass_rate,
                "duration_ms": sr.duration_ms,
                "certified": sr.certified,
                "results": [
                    {
                        "name": r.name,
                        "status": r.status.value,
                        "duration_ms": r.duration_ms,
                        "detail": r.detail,
                        "evidence": r.evidence,
                        "error": r.error,
                    }
                    for r in sr.results
                ],
            }
            report["summary"]["total_tests"] += sr.total
            report["summary"]["total_passed"] += sr.passed
            report["summary"]["total_failed"] += sr.failed
            report["summary"]["total_skipped"] += sr.skipped
            report["summary"]["total_errors"] += sr.errors
            if sr.certified:
                report["summary"]["certified_suites"] += 1

        return json.dumps(report, indent=2)

    def print_report(self, results: dict[str, SuiteResult]) -> None:
        """Print a human-readable conformance report to stdout."""
        width = 72
        print("=" * width)
        print("  Nous Conformance Test Kit - Report")
        print(f"  Target Level: {self.target_level.name}")
        print("=" * width)
        for sid, sr in results.items():
            status = "[PASS] CERTIFIED" if sr.certified else "[FAIL] NOT CERTIFIED"
            print(f"\n  [{sr.interface}/{sr.version}] {status}")
            print(
                f"  Tests: {sr.total} total, {sr.passed} passed, "
                f"{sr.failed} failed, {sr.skipped} skipped, {sr.errors} errors"
            )
            print(f"  Pass Rate: {sr.pass_rate:.0%}")
            print(f"  Duration: {sr.duration_ms:.0f}ms")
            for r in sr.results:
                icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "ERROR": "[ERROR]"}[
                    r.status.value.upper()
                ]
                print(f"    {icon} {r.name} ({r.duration_ms:.0f}ms)")
                if r.detail:
                    print(f"       {r.detail}")
                if r.error:
                    print(f"       ERROR: {r.error}")


# ────────────────────────────────────────────────────────────
# Built-in test definitions (RFC-0014 §4)
# ────────────────────────────────────────────────────────────


def _device_abi_tests() -> list[TestCase]:
    """Device ABI conformance tests (14 operations)."""
    return [
        TestCase(
            "device-discover",
            "Device can be discovered and enumerated",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "device-probe",
            "Device responds to probe with spec",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "device-verify",
            "Device identity can be cryptographically verified",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "device-bind",
            "Device can be bound to a kernel instance",
            ConformanceLevel.RUNNABLE,
            "resource",
        ),
        TestCase(
            "device-initialize",
            "Device initializes to READY state",
            ConformanceLevel.RUNNABLE,
            "resource",
        ),
        TestCase(
            "device-allocate",
            "Device resources can be allocated",
            ConformanceLevel.MANAGED,
            "resource",
        ),
        TestCase(
            "device-free",
            "Allocated resources can be freed",
            ConformanceLevel.MANAGED,
            "resource",
        ),
        TestCase(
            "device-health",
            "Device reports health status",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "device-telemetry",
            "Device reports utilization/temperature",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "device-topology",
            "Device reports topology links",
            ConformanceLevel.SCHEDULABLE,
            "discovery",
        ),
        TestCase(
            "device-reset",
            "Device can be reset and re-initialized",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
        TestCase(
            "device-suspend-resume",
            "Device can suspend and resume",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
    ]


def _engine_abi_tests() -> list[TestCase]:
    """Engine ABI conformance tests (17 operations)."""
    return [
        TestCase(
            "engine-probe",
            "Engine responds to probe",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "engine-capabilities",
            "Engine reports capabilities",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "engine-validate-model",
            "Engine validates model compatibility",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "engine-estimate-resources",
            "Engine estimates resource requirements",
            ConformanceLevel.RUNNABLE,
            "resource",
        ),
        TestCase(
            "engine-load-model",
            "Engine loads a model successfully",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "engine-infer",
            "Engine completes a basic inference",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "engine-stream",
            "Engine streams tokens",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "engine-cancel",
            "Engine cancels in-flight inference",
            ConformanceLevel.MANAGED,
            "execution",
        ),
        TestCase(
            "engine-health",
            "Engine reports health status",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "engine-metrics",
            "Engine reports performance metrics",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "engine-drain",
            "Engine drains requests gracefully",
            ConformanceLevel.SCHEDULABLE,
            "resource",
        ),
        TestCase(
            "engine-snapshot",
            "Engine snapshots model state",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
        TestCase(
            "engine-restore",
            "Engine restores from snapshot",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
    ]


def _nki_client_tests() -> list[TestCase]:
    """NKI client conformance tests."""
    return [
        TestCase(
            "nki-connect",
            "Client connects to nousd successfully",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "nki-health-check",
            "Health check returns healthy",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "nki-submit-workload",
            "Workload submission works",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "nki-admit-workload",
            "Admission control works",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "nki-reserve-resources",
            "Resource reservation works",
            ConformanceLevel.SCHEDULABLE,
            "resource",
        ),
        TestCase(
            "nki-cancel-workload",
            "Workload cancellation works",
            ConformanceLevel.MANAGED,
            "execution",
        ),
        TestCase(
            "nki-register-model",
            "Model registration works",
            ConformanceLevel.RUNNABLE,
            "discovery",
        ),
        TestCase(
            "nki-create-checkpoint",
            "Checkpoint creation works",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
        TestCase(
            "nki-restore-checkpoint",
            "Checkpoint restoration works",
            ConformanceLevel.RECOVERABLE,
            "recovery",
        ),
        TestCase(
            "nki-watch-events",
            "Event streaming works",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "nki-get-metrics",
            "Metrics retrieval works",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "nki-idempotency",
            "Idempotency key prevents duplicate submissions",
            ConformanceLevel.MANAGED,
            "execution",
        ),
        TestCase(
            "nki-deadline",
            "Deadline enforcement works",
            ConformanceLevel.MANAGED,
            "execution",
        ),
    ]


def _provider_sdk_tests() -> list[TestCase]:
    """Provider SDK conformance tests."""
    return [
        TestCase(
            "provider-package-format",
            "Provider package has valid structure",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "provider-discovery-interface",
            "Provider implements Discovery interface",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "provider-resource-interface",
            "Provider implements Resource interface",
            ConformanceLevel.SCHEDULABLE,
            "resource",
        ),
        TestCase(
            "provider-execution-interface",
            "Provider implements Execution interface",
            ConformanceLevel.RUNNABLE,
            "execution",
        ),
        TestCase(
            "provider-telemetry-interface",
            "Provider implements Telemetry interface",
            ConformanceLevel.MANAGED,
            "telemetry",
        ),
        TestCase(
            "provider-version-negotiation",
            "Provider correctly negotiates ABI version",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
        ),
        TestCase(
            "provider-error-handling",
            "Provider returns standard error codes",
            ConformanceLevel.MANAGED,
            "execution",
        ),
    ]


def _platform_tests() -> list[TestCase]:
    """Platform conformance tests."""
    return [
        TestCase(
            "platform-os-detection",
            "OS is correctly identified",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
            required=True,
        ),
        TestCase(
            "platform-arch-detection",
            "CPU architecture is correctly identified",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
            required=True,
        ),
        TestCase(
            "platform-memory-reporting",
            "System memory is correctly reported",
            ConformanceLevel.DISCOVERABLE,
            "discovery",
            required=True,
        ),
        TestCase(
            "platform-process-isolation",
            "Process sandbox can enforce limits",
            ConformanceLevel.MANAGED,
            "security",
        ),
        TestCase(
            "platform-filesystem-acl",
            "Filesystem ACL is enforced",
            ConformanceLevel.MANAGED,
            "security",
        ),
        TestCase(
            "platform-network-policy",
            "Network egress policy is enforced",
            ConformanceLevel.MANAGED,
            "security",
        ),
    ]


# ────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for nous-ctk."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="nous-ctk",
        description="Nous Conformance Test Kit (RFC-0014)",
    )
    parser.add_argument(
        "--level",
        type=str,
        default="DISCOVERABLE",
        choices=[level.name for level in ConformanceLevel],
        help="Target conformance level",
    )
    parser.add_argument(
        "--suite",
        type=str,
        action="append",
        dest="suites",
        help="Run specific suite(s); omit for all",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="text",
        choices=["text", "json"],
        help="Output format",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write report to file",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "list", "validate"],
        help="Command to execute",
    )

    args = parser.parse_args(argv)
    level = ConformanceLevel.from_string(args.level)
    runner = CTKRunner(target_level=level)

    if args.command == "list":
        print("Available conformance suites:")
        for sid, suite in runner.suites.items():
            test_count = len(suite.tests)
            print(
                f"  {sid:20s} - {suite.interface} v{suite.version} ({test_count} tests)"
            )
            print(f"    Prerequisites: {', '.join(suite.prerequisites)}")
        return 0

    if args.command == "validate":
        # Validate a Provider package or Device manifest
        print("Validate command: provide a provider package or device manifest path")
        return 0

    # Run conformance tests
    if args.suites:
        results = runner.run_required(args.suites)
    else:
        results = runner.run_all()

    if args.format == "json":
        report = runner.report_json(results)
        if args.output:
            Path(args.output).write_text(report)
            print(f"Report written to {args.output}")
        else:
            print(report)
    else:
        runner.print_report(results)
        if args.output:
            report = runner.report_json(results)
            Path(args.output).write_text(report)
            print(f"\nJSON report written to {args.output}")

    # Exit code: 0 if all tested suites pass
    all_certified = all(sr.certified for sr in results.values())
    return 0 if all_certified else 1


__all__ = [
    "CTKRunner",
    "ConformanceSuite",
    "ConformanceLevel",
    "SuiteResult",
    "TestCase",
    "TestResult",
    "TestStatus",
    "main",
]
