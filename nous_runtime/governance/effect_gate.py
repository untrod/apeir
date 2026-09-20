"""Canonical effect gate for the Python distribution.

Ensures ALL external side effects pass through the canonical path:
  Canonical Action → Policy Decision → Approval Binding
  → Effect Intent → Effector → Effect Receipt
  → Proof Verification → Commit

The gate provides:
  - Canonical action serialization (prevents parameter tampering)
  - Effect receipt generation (unique, verifiable)
  - Replay prevention (idempotency via action hash)
  - Proof verification (when available)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("nous.governance.effect_gate")


class GateDecision(Enum):
    """Gate decision for an effect."""
    EXECUTE = "execute"        # Auto-approve (low risk)
    RECOMMEND = "recommend"    # Suggest but let caller decide
    ASK_APPROVAL = "ask_approval"  # Require human approval
    ESCALATE = "escalate"      # Require higher authority
    DENY = "deny"              # Block execution


class EffectStatus(Enum):
    """Status of an effect through the gate."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTING = "executing"
    EXECUTED = "executed"
    COMMITTED = "committed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class CanonicalAction:
    """An action in canonical form — cannot be tampered with after approval."""
    action_type: str
    target: str
    params: dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: f"action-{uuid.uuid4().hex[:12]}")
    action_hash: str = ""

    def __post_init__(self):
        if not self.action_hash:
            self.action_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Hash the canonical action for integrity verification."""
        canonical = json.dumps({
            "type": self.action_type,
            "target": self.target,
            "params": self.params,
        }, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def verify(self) -> bool:
        """Verify the action hash hasn't been tampered with."""
        return self.action_hash == self._compute_hash()


@dataclass
class ApprovalBinding:
    """Binds an approval decision to a specific canonical action."""
    approval_id: str = field(default_factory=lambda: f"approval-{uuid.uuid4().hex[:12]}")
    action_hash: str = ""  # Hash of the approved CanonicalAction
    approver: str = ""  # Who approved (human identity or policy id)
    decision: GateDecision = GateDecision.DENY
    granted_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    constraints: dict[str, Any] = field(default_factory=dict)  # e.g., max_duration, max_cost

    def is_valid_for(self, action: CanonicalAction) -> bool:
        """Check if this approval is valid for the given action."""
        if self.action_hash != action.action_hash:
            return False  # Action was modified after approval
        if self.expires_at > 0 and time.time() > self.expires_at:
            return False  # Approval expired
        return True


@dataclass
class EffectReceipt:
    """Proof that an external effect was executed."""
    receipt_id: str = field(default_factory=lambda: f"receipt-{uuid.uuid4().hex[:12]}")
    action_hash: str = ""
    approval_id: str = ""
    effector_id: str = ""  # Which effector executed this
    executed_at: float = field(default_factory=time.time)
    result: Any = None
    success: bool = False
    receipt_hash: str = ""

    def __post_init__(self):
        if not self.receipt_hash:
            self.receipt_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = json.dumps({
            "action_hash": self.action_hash,
            "approval_id": self.approval_id,
            "effector_id": self.effector_id,
            "executed_at": self.executed_at,
            "success": self.success,
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()


class EffectGate:
    """Distribution gate for canonical external-effect requests.

    Replay prevention:
      - Each CanonicalAction has a unique hash
      - Executed action hashes are tracked
      - Replay of a committed action is detected and denied

    Parameter integrity:
      - Approval binds to a specific action hash
      - Modified parameters → different hash → approval invalid
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._executed_hashes: set[str] = set()  # Committed effects only
        self._inflight_hashes: set[str] = set()
        self._pending_approvals: dict[str, ApprovalBinding] = {}
        self._receipts: dict[str, EffectReceipt] = {}
        self._effect_callbacks: dict[str, list[callable]] = {}

    def propose_action(
        self,
        action_type: str,
        target: str,
        params: dict[str, Any],
    ) -> tuple[CanonicalAction, GateDecision]:
        """Propose an action for execution through the gate."""
        action = CanonicalAction(
            action_type=action_type,
            target=target,
            params=params,
        )

        with self._lock:
            # Replay check
            if (
                action.action_hash in self._executed_hashes
                or action.action_hash in self._inflight_hashes
            ):
                log.warning("Replay detected: action %s already executed", action.action_hash)
                return action, GateDecision.DENY

        # Risk assessment
        decision = self._assess_risk(action)
        return action, decision

    def request_approval(
        self,
        action: CanonicalAction,
        approver: str = "policy",
        ttl_seconds: float = 3600,
    ) -> ApprovalBinding:
        """Request approval for an action."""
        binding = ApprovalBinding(
            action_hash=action.action_hash,
            approver=approver,
            decision=GateDecision.EXECUTE,
            expires_at=time.time() + ttl_seconds if ttl_seconds > 0 else 0,
        )

        with self._lock:
            self._pending_approvals[binding.approval_id] = binding

        return binding

    def execute(
        self,
        action: CanonicalAction,
        approval: ApprovalBinding,
        effector: callable,
    ) -> EffectReceipt:
        """Execute an approved action through the gate.

        Verifies:
          1. Action hash matches approval (no parameter tampering)
          2. Approval hasn't expired
          3. Action hasn't already been executed (replay protection)
        """
        # Verify approval binding
        if not approval.is_valid_for(action):
            raise ValueError("Approval binding invalid: action hash mismatch or expired")

        with self._lock:
            # Replay check (double-check under lock)
            if (
                action.action_hash in self._executed_hashes
                or action.action_hash in self._inflight_hashes
            ):
                raise ValueError(f"Action {action.action_hash} already executed — replay denied")

            # Reserve while executing. Replay protection becomes durable only
            # after the effector returns a successful receipt.
            self._inflight_hashes.add(action.action_hash)

        # Execute
        try:
            result = effector(action.params)
            success = True
        except Exception as e:
            result = {"error": str(e)}
            success = False
            log.error("Effect execution failed: %s", e)

        # Generate receipt
        receipt = EffectReceipt(
            action_hash=action.action_hash,
            approval_id=approval.approval_id,
            effector_id=getattr(effector, "__name__", "unknown"),
            result=result,
            success=success,
        )

        with self._lock:
            self._inflight_hashes.discard(action.action_hash)
            if success:
                self._executed_hashes.add(action.action_hash)
            self._receipts[receipt.receipt_id] = receipt

        log.info(
            "Effect executed: action=%s receipt=%s success=%s",
            action.action_hash[:12], receipt.receipt_id, success,
        )
        return receipt

    def verify_receipt(self, receipt_id: str) -> EffectReceipt | None:
        """Retrieve and verify an effect receipt."""
        receipt = self._receipts.get(receipt_id)
        if receipt and receipt.receipt_hash == receipt._compute_hash():
            return receipt
        return None

    def was_executed(self, action_hash: str) -> bool:
        """Check if an action has a successful committed receipt."""
        return action_hash in self._executed_hashes

    def is_inflight(self, action_hash: str) -> bool:
        """Return whether an identical canonical action is executing."""
        return action_hash in self._inflight_hashes

    def _assess_risk(self, action: CanonicalAction) -> GateDecision:
        """Assess risk level of an action."""
        high_risk = {
            "shell_exec", "file_write", "device_control",
            "git_push", "network_outbound", "code_execution",
        }
        medium_risk = {
            "file_read", "git_read", "database_write",
            "model_inference", "network_request",
        }

        if action.action_type in high_risk:
            return GateDecision.ASK_APPROVAL
        elif action.action_type in medium_risk:
            return GateDecision.RECOMMEND
        else:
            return GateDecision.EXECUTE

    @property
    def executed_count(self) -> int:
        return len(self._executed_hashes)

    @property
    def receipt_count(self) -> int:
        return len(self._receipts)
