# -*- coding: utf-8 -*-
"""Runtime Inspector diagnostic rules."""

from __future__ import annotations

import os
from pathlib import Path

from nous_runtime.inspector.models import DiagnosticFinding, InspectorSnapshot
from nous_runtime.inspector.snapshot import snapshot


def diagnose(snap: InspectorSnapshot | None = None) -> list[DiagnosticFinding]:
    """Run read-only diagnostic rules over an inspector snapshot."""
    snap = snap or snapshot()
    findings: list[DiagnosticFinding] = []

    for error in snap.runtime.errors:
        findings.append(
            DiagnosticFinding(
                code="RUNTIME_SNAPSHOT_ERROR",
                severity="warning",
                component="runtime",
                message=error,
                remediation="Run `nous inspect diagnose --json` for details.",
            )
        )

    if not snap.runtime.workspace:
        findings.append(
            DiagnosticFinding(
                code="WORKSPACE_NOT_FOUND",
                severity="warning",
                component="workspace",
                message="No .nous workspace found from the current directory.",
                remediation="Run `nous project init` in the project root.",
            )
        )
    else:
        _workspace_findings(Path(snap.runtime.workspace), findings)

    for provider in snap.providers:
        if provider.status not in ("ok", "healthy", "unknown"):
            findings.append(
                DiagnosticFinding(
                    code="PROVIDER_UNAVAILABLE",
                    severity="error" if provider.status == "down" else "warning",
                    component="provider",
                    message=f"Provider {provider.provider_id} status is {provider.status}.",
                    remediation="Check provider configuration and credentials.",
                    details=provider.to_dict(),
                )
            )

    for cap in snap.capabilities:
        if not cap.available:
            code = "CAPABILITY_DEPENDENCY_MISSING"
            if "disabled" in cap.reason.lower():
                code = "CAPABILITY_UNAVAILABLE"
            findings.append(
                DiagnosticFinding(
                    code=code,
                    severity="warning",
                    component="capability",
                    message=f"Capability {cap.capability_id} is unavailable: {cap.reason or 'unknown reason'}.",
                    remediation="Run `nous capability availability` and configure the required provider.",
                    details=cap.to_dict(),
                )
            )

    for task in snap.tasks:
        status = task.status.lower()
        if status == "failed":
            findings.append(
                DiagnosticFinding(
                    code="TASK_FAILED",
                    severity="error",
                    component="task",
                    message=f"Task {task.task_id} failed.",
                    remediation="Inspect the task observation chain.",
                    details=task.to_dict(),
                )
            )
        elif status in ("blocked", "timeout", "timed_out"):
            findings.append(
                DiagnosticFinding(
                    code="TASK_BLOCKED",
                    severity="error",
                    component="task",
                    message=f"Task {task.task_id} is blocked or timed out.",
                    remediation="Check task dependencies and provider availability.",
                    details=task.to_dict(),
                )
            )

    for observation in snap.observations:
        status = observation.status.lower()
        if status in ("failed", "error", "timeout"):
            findings.append(
                DiagnosticFinding(
                    code="OBSERVATION_FAILED",
                    severity="error",
                    component="observation",
                    message=f"Observation {observation.observation_id} is {observation.status}.",
                    remediation="Inspect the linked provider, capability, and memory record.",
                    details=observation.to_dict(),
                )
            )

    if snap.memory.errors:
        for error in snap.memory.errors:
            findings.append(
                DiagnosticFinding(
                    code="MEMORY_UNAVAILABLE",
                    severity="warning",
                    component="memory",
                    message=error,
                    remediation="Create or repair the .nous workspace.",
                )
            )
    for stream in snap.memory.missing_streams:
        findings.append(
            DiagnosticFinding(
                code="MEMORY_FILE_MISSING",
                severity="warning",
                component="memory",
                message=f"Memory stream {stream} is missing.",
                remediation="Run `nous project init` to create missing workspace files.",
                details={"stream": stream},
            )
        )
    for invalid in snap.memory.invalid_records:
        findings.append(
            DiagnosticFinding(
                code="MEMORY_INVALID_RECORD",
                severity="error",
                component="memory",
                message="Invalid JSONL record detected.",
                remediation="Repair or remove the invalid JSONL line.",
                details=invalid,
            )
        )
    for broken in snap.memory.broken_supersedes:
        findings.append(
            DiagnosticFinding(
                code="MEMORY_SUPERSEDES_BROKEN",
                severity="error",
                component="memory",
                message="Memory supersedes chain references a missing record.",
                remediation="Repair the fact chain or append a corrected fact.",
                details=broken,
            )
        )
    for cycle in snap.memory.supersedes_cycles:
        findings.append(
            DiagnosticFinding(
                code="MEMORY_SUPERSEDES_CYCLE",
                severity="error",
                component="memory",
                message="Memory supersedes chain contains a cycle.",
                remediation="Repair one link in the cycle by appending a corrected fact.",
                details=cycle,
            )
        )
    for conflict in snap.memory.stable_key_conflicts:
        findings.append(
            DiagnosticFinding(
                code="MEMORY_STABLE_KEY_CONFLICT",
                severity="warning",
                component="memory",
                message=f"Stable key {conflict.get('stable_key')} has multiple values.",
                remediation="Confirm whether the newer fact intentionally supersedes the older one.",
                details=conflict,
            )
        )

    for device in snap.devices:
        if not device.online:
            findings.append(
                DiagnosticFinding(
                    code="DEVICE_UNAVAILABLE",
                    severity="info",
                    component="device",
                    message=f"Device {device.device_id} is offline.",
                    remediation="Reconnect the device or wait for heartbeat.",
                    details=device.to_dict(),
                )
            )

    # Show actionable failures before advisory dependency warnings. A stable
    # severity order keeps terminal output useful even when it is truncated.
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        findings,
        key=lambda item: (
            severity_order.get(item.severity.lower(), 3),
            item.component,
            item.code,
        ),
    )


def _workspace_findings(workspace: Path, findings: list[DiagnosticFinding]) -> None:
    required = ("project.json", "config.json", "tasks.json")
    for filename in required:
        if not (workspace / filename).is_file():
            findings.append(
                DiagnosticFinding(
                    code="CONFIG_MISSING",
                    severity="warning",
                    component="config",
                    message=f"Workspace file {filename} is missing.",
                    remediation="Run `nous project init` or restore the missing file.",
                    details={"file": filename},
                )
            )

    try:
        probe = workspace / ".inspect_write_probe"
        with probe.open("w", encoding="utf-8") as fh:
            fh.write("")
        os.remove(probe)
    except Exception as exc:
        findings.append(
            DiagnosticFinding(
                code="WORKSPACE_PERMISSION_ERROR",
                severity="error",
                component="workspace",
                message=f"Workspace is not writable: {exc}",
                remediation="Fix filesystem permissions for the .nous directory.",
            )
        )
