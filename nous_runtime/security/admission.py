# -*- coding: utf-8 -*-
"""
Admission Control Pipeline for Nous Runtime.

Implements §9 (Capability Security Execution System) and §18 (Security & Trust).

Every capability invocation passes through this pipeline:
    Request → Authenticate → Authorize → Risk Check → Budget Check → Execute → Audit

Design principle (§3.6): Default minimum privilege — every model, agent, and task
gets only the permissions needed for the current objective.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.security.admission")


# Risk Level

class RiskLevel(str, Enum):
    """Risk levels per master plan §9.3."""
    READ_ONLY = "read_only"    # Auto-execute if policy allows
    LOW = "low"                # Auto-execute per user settings
    MEDIUM = "medium"          # Requires one-time approval
    HIGH = "high"              # Must show full operation details
    CRITICAL = "critical"      # Default deny or enhanced confirmation


AUTO_EXECUTE_RISK = {RiskLevel.READ_ONLY, RiskLevel.LOW}
APPROVAL_REQUIRED_RISK = {RiskLevel.MEDIUM, RiskLevel.HIGH}
DENY_DEFAULT_RISK = {RiskLevel.CRITICAL}


# Admission Request

@dataclass
class AdmissionRequest:
    """A capability invocation going through the admission pipeline."""
    request_id: str = field(default_factory=lambda: make_id(prefix="adm"))
    capability_id: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    params: dict[str, Any] = field(default_factory=dict)

    # Context
    user_id: str = ""
    node_id: str = ""
    task_id: str = ""
    conversation_id: str = ""
    trace_id: str = ""

    # Budget
    estimated_cost_cents: int = 0
    estimated_tokens: int = 0

    # Result
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Admission Result

@dataclass
class AdmissionResult:
    """Result of admission control check."""
    allowed: bool = False
    reason: str = ""
    requires_approval: bool = False
    approval_token: str = ""             # HMAC-signed approval if granted
    budget_consumed: dict[str, int] = field(default_factory=dict)
    audit_record: dict[str, Any] = field(default_factory=dict)


# Admission Pipeline

class AdmissionPipeline:
    """Multi-stage admission control for capability execution.

    Stages:
        1. Authenticate — verify caller identity
        2. Authorize  — check capability grants
        3. Risk       — evaluate risk level
        4. Budget     — check budget limits
        5. Execute    — (delegated to capability)
        6. Audit      — record decision
    """

    def __init__(self):
        self._pre_hooks: list[Callable[[AdmissionRequest], AdmissionResult | None]] = []
        self._post_hooks: list[Callable[[AdmissionRequest, AdmissionResult], None]] = []
        self._budget_checker: Callable[[str, int], bool] | None = None  # (user_id, cost) -> ok

    def add_pre_hook(self, hook: Callable[[AdmissionRequest], AdmissionResult | None]) -> None:
        """Add a pre-execution check. Return AdmissionResult to short-circuit."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: Callable[[AdmissionRequest, AdmissionResult], None]) -> None:
        """Add a post-execution audit hook."""
        self._post_hooks.append(hook)

    def check(self, request: AdmissionRequest,
              grants: list[Any] | None = None,
              budget_remaining_cents: int = 0) -> AdmissionResult:
        """Run the full admission pipeline for a capability request."""

        # Stage 1: Authenticate
        if not request.user_id and not request.node_id:
            return AdmissionResult(
                allowed=False,
                reason="No identity provided for authentication",
            )

        # Stage 2: Authorize — check grants
        if grants is not None:
            active_grants = [g for g in grants if g.is_active and not g.is_exhausted]
            matching = [g for g in active_grants
                        if g.capability_id == request.capability_id
                        or g.capability_id == "*"]
            if not matching:
                return AdmissionResult(
                    allowed=False,
                    reason=f"No active grant for '{request.capability_id}'",
                )

        # Stage 3: Risk check
        if request.risk_level == RiskLevel.CRITICAL:
            return AdmissionResult(
                allowed=False,
                reason="CRITICAL risk — default deny, requires explicit override",
                requires_approval=True,
            )
        elif request.risk_level in APPROVAL_REQUIRED_RISK:
            requires_approval = True
        else:
            requires_approval = False

        # Stage 4: Budget check
        if request.estimated_cost_cents > 0:
            if budget_remaining_cents > 0 and request.estimated_cost_cents > budget_remaining_cents:
                return AdmissionResult(
                    allowed=False,
                    reason=f"Budget exceeded: {request.estimated_cost_cents}c > {budget_remaining_cents}c remaining",
                )

        # Stage 5: Pre-hooks
        for hook in self._pre_hooks:
            result = hook(request)
            if result is not None:
                return result  # Short-circuit

        # Approved
        audit = {
            "request_id": request.request_id,
            "capability_id": request.capability_id,
            "risk_level": request.risk_level.value,
            "user_id": request.user_id,
            "node_id": request.node_id,
            "task_id": request.task_id,
            "allowed": True,
            "requires_approval": requires_approval,
            "timestamp": request.timestamp,
        }

        result = AdmissionResult(
            allowed=True,
            reason="OK",
            requires_approval=requires_approval,
            budget_consumed={"estimated_cost_cents": request.estimated_cost_cents},
            audit_record=audit,
        )

        # Stage 6: Post-hooks (audit)
        for hook in self._post_hooks:
            try:
                hook(request, result)
            except Exception as e:
                log.error("Post-hook failed: %s", e)

        return result

    def quick_check(self, capability_id: str, risk: RiskLevel,
                    user_id: str = "") -> AdmissionResult:
        """Fast path for simple permission checks."""
        return self.check(AdmissionRequest(
            capability_id=capability_id,
            risk_level=risk,
            user_id=user_id,
        ))


# Default risk classifier

_DEFAULT_RISK_MAP: dict[str, RiskLevel] = {
    # System
    "system.health": RiskLevel.READ_ONLY,
    "system.status": RiskLevel.READ_ONLY,
    "system.config.read": RiskLevel.READ_ONLY,
    "system.config.write": RiskLevel.HIGH,
    "system.restart": RiskLevel.HIGH,

    # Project / files
    "project.read_file": RiskLevel.READ_ONLY,
    "project.list_files": RiskLevel.READ_ONLY,
    "project.write_file": RiskLevel.MEDIUM,
    "project.delete_file": RiskLevel.HIGH,
    "project.run_tests": RiskLevel.LOW,
    "project.run_script": RiskLevel.MEDIUM,

    # Git
    "git.status": RiskLevel.READ_ONLY,
    "git.diff": RiskLevel.READ_ONLY,
    "git.commit": RiskLevel.MEDIUM,
    "git.push": RiskLevel.HIGH,

    # Model
    "model.run_inference": RiskLevel.LOW,
    "model.download": RiskLevel.MEDIUM,
    "model.delete": RiskLevel.HIGH,

    # Device
    "device.get_status": RiskLevel.READ_ONLY,
    "sensor.read": RiskLevel.READ_ONLY,
    "camera.capture": RiskLevel.MEDIUM,
    "device.restart": RiskLevel.HIGH,
    "device.calibrate": RiskLevel.HIGH,
    "robot.move": RiskLevel.HIGH,
    "plc.write_register": RiskLevel.CRITICAL,

    # Service / infra
    "service.health": RiskLevel.READ_ONLY,
    "service.restart": RiskLevel.HIGH,
    "service.deploy": RiskLevel.CRITICAL,

    # Shell
    "shell.execute": RiskLevel.HIGH,
    "shell.execute_sandboxed": RiskLevel.MEDIUM,
}


def classify_risk(capability_id: str) -> RiskLevel:
    """Map a capability ID to its default risk level."""
    # Exact match
    if capability_id in _DEFAULT_RISK_MAP:
        return _DEFAULT_RISK_MAP[capability_id]

    # Prefix match (e.g., "project.*" → MEDIUM as default)
    prefix = capability_id.split(".")[0] if "." in capability_id else capability_id
    prefix_defaults = {
        "project": RiskLevel.MEDIUM,
        "git": RiskLevel.MEDIUM,
        "model": RiskLevel.LOW,
        "device": RiskLevel.HIGH,
        "sensor": RiskLevel.READ_ONLY,
        "camera": RiskLevel.MEDIUM,
        "robot": RiskLevel.HIGH,
        "plc": RiskLevel.CRITICAL,
        "service": RiskLevel.HIGH,
        "shell": RiskLevel.HIGH,
        "system": RiskLevel.MEDIUM,
    }
    return prefix_defaults.get(prefix, RiskLevel.MEDIUM)
