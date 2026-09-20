# -*- coding: utf-8 -*-
"""
ApprovalBroker — unified approval handling for the Runtime.

All approval requests flow through this broker. Consumers (terminal, API,
desktop, mobile) register for approval events and return decisions through
the same interface. The external agent must never approve its own request.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalScope,
    AuthorizationContext,
    AuthorizationLease,
    _new_id,
)
from nous_runtime.governance.store import GovernanceStore

_log = logging.getLogger("nous.governance.broker")


class ApprovalStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalEvidence:
    """Evidence attached to an approval request for audit."""

    def __init__(
        self,
        *,
        command_preview: str = "",
        affected_files: tuple[str, ...] = (),
        workspace_path: str = "",
        capability_request: str = "",
        risk_envelope: dict[str, Any] | None = None,
    ):
        self.command_preview = command_preview
        self.affected_files = tuple(affected_files)
        self.workspace_path = workspace_path
        self.capability_request = capability_request
        self.risk_envelope = dict(risk_envelope or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_preview": self.command_preview,
            "affected_files": list(self.affected_files),
            "workspace_path": self.workspace_path,
            "capability_request": self.capability_request,
            "risk_envelope": self.risk_envelope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalEvidence":
        return cls(
            command_preview=str(data.get("command_preview") or ""),
            affected_files=tuple(data.get("affected_files") or ()),
            workspace_path=str(data.get("workspace_path") or ""),
            capability_request=str(data.get("capability_request") or ""),
            risk_envelope=dict(data.get("risk_envelope") or {}),
        )


class ApprovalPolicy:
    """User-configurable approval policy for an agent or capability."""

    def __init__(
        self,
        *,
        policy_id: str = "",
        agent_id: str = "",
        capability_id: str = "",
        scope: str = "ask_per_command",  # always_allow | always_ask | ask_once_per_run | ask_per_command | policy_controlled
        max_auto_approve_risk: str = "low",  # low | medium | high
        auto_approve_read_only: bool = False,
        auto_approve_tests: bool = False,
        max_daily_approvals: int = 50,
        require_confirmation_for_policy_change: bool = True,
        created_at: str = "",
        updated_at: str = "",
    ):
        self.policy_id = policy_id or _new_id("pol")
        self.agent_id = agent_id
        self.capability_id = capability_id
        self.scope = scope
        self.max_auto_approve_risk = max_auto_approve_risk
        self.auto_approve_read_only = auto_approve_read_only
        self.auto_approve_tests = auto_approve_tests
        self.max_daily_approvals = max_daily_approvals
        self.require_confirmation_for_policy_change = require_confirmation_for_policy_change
        self.created_at = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "agent_id": self.agent_id,
            "capability_id": self.capability_id,
            "scope": self.scope,
            "max_auto_approve_risk": self.max_auto_approve_risk,
            "auto_approve_read_only": self.auto_approve_read_only,
            "auto_approve_tests": self.auto_approve_tests,
            "max_daily_approvals": self.max_daily_approvals,
            "require_confirmation_for_policy_change": self.require_confirmation_for_policy_change,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalPolicy":
        return cls(
            policy_id=str(data.get("policy_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            scope=str(data.get("scope") or "ask_per_command"),
            max_auto_approve_risk=str(data.get("max_auto_approve_risk") or "low"),
            auto_approve_read_only=bool(data.get("auto_approve_read_only", False)),
            auto_approve_tests=bool(data.get("auto_approve_tests", False)),
            max_daily_approvals=int(data.get("max_daily_approvals") or 50),
            require_confirmation_for_policy_change=bool(data.get("require_confirmation_for_policy_change", True)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def evaluate(self, risk_level: str, is_read_only: bool, is_test: bool) -> str:
        """Evaluate whether a proposed action should be auto-approved.

        Returns: "allow" | "ask"
        """
        if risk_level == "critical":
            return "ask"

        if self.scope == "always_allow":
            return "allow"

        if self.scope == "always_ask":
            return "ask"

        if self.max_auto_approve_risk == "high":
            return "allow"
        if self.max_auto_approve_risk == "medium" and risk_level in ("low", "medium"):
            return "allow"
        if self.max_auto_approve_risk == "low" and risk_level == "low":
            return "allow"

        if is_read_only and self.auto_approve_read_only:
            return "allow"
        if is_test and self.auto_approve_tests:
            return "allow"

        return "ask"


class ApprovalBroker:
    """Unified approval broker for the Runtime.

    All approval requests flow through this broker. It:
    - Creates approval requests from gate decisions
    - Pauses runs while approval is pending
    - Emits approval.requested / approval.granted / approval.denied
    - Expires old approvals
    - Prevents reuse outside the bound run
    - Persists audit records
    - Supports terminal, API, desktop, and mobile consumers
    - Prevents the external agent from approving its own request
    """

    def __init__(self, store: GovernanceStore | None = None):
        self._store = store or GovernanceStore()
        self._pending: dict[str, ApprovalRequest] = {}
        self._policies: dict[str, ApprovalPolicy] = {}
        self._daily_counts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._listeners: list[callable] = []

    def register_listener(self, callback: callable) -> None:
        """Register a callback for approval events.

        The callback receives (event_type: str, data: dict).
        """
        self._listeners.append(callback)

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        for cb in self._listeners:
            try:
                cb(event_type, data)
            except Exception:
                pass

    def request_approval(
        self,
        *,
        run_id: str,
        task_id: str,
        proposal: ActionProposal,
        context: AuthorizationContext,
        evidence: ApprovalEvidence | None = None,
        requester: str = "",
        ttl_hours: int = 24,
    ) -> ApprovalRequest:
        """Create an approval request for a proposed action.

        This pauses the run and emits approval.requested.
        """
        from nous_runtime.governance.risk_engine import assess_risk

        risk = assess_risk(proposal, context)

        request = ApprovalRequest(
            request_id=_new_id("apr"),
            proposal_hash=proposal.proposal_hash,
            summary=f"{proposal.action_type}: {proposal.capability_id}",
            risk_summary=f"Risk: {risk.aggregate_risk_class}",
            scope_summary=f"Workspace: {proposal.target_workspace}, "
                          f"Resources: {len(proposal.affected_resources)}",
            status=ApprovalStatus.PENDING.value,
            requested_by=requester or context.subject_id,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%SZ") if ttl_hours else "",
        )

        with self._lock:
            self._pending[request.request_id] = request

        persisted = request.to_dict()
        persisted["run_id"] = run_id
        persisted["task_id"] = task_id
        if not self._store.save_approval_request(persisted):
            with self._lock:
                self._pending.pop(request.request_id, None)
            raise RuntimeError("Failed to persist approval request")

        self._emit("approval.requested", {
            "request_id": request.request_id,
            "run_id": run_id,
            "task_id": task_id,
            "summary": request.summary,
            "risk_summary": request.risk_summary,
            "scope_summary": request.scope_summary,
            "evidence": evidence.to_dict() if evidence else {},
        })

        _log.info("Approval requested: %s for run %s", request.request_id, run_id)
        return request

    def approve(
        self,
        request_id: str,
        *,
        approver_id: str,
        scope: str = "once",
        reason: str = "",
        prevent_self_approval: bool = True,
        requester_id: str = "",
    ) -> ApprovalResponse:
        """Approve a pending approval request.

        If prevent_self_approval is True and approver_id matches requester_id,
        the approval is rejected.
        """
        with self._lock:
            req = self._pending.get(request_id)
            if not req:
                req_data = self._store.get_approval_request(request_id)
                if req_data:
                    req = ApprovalRequest.from_dict(req_data)

            if not req:
                raise ValueError(f"Approval request {request_id} not found")

            if req.status != ApprovalStatus.PENDING.value:
                raise ValueError(
                    f"Approval request {request_id} is not PENDING (status={req.status})"
                )

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if req.expires_at and req.expires_at <= now:
                if not self._store.expire_approval(request_id):
                    raise ValueError(f"Approval request {request_id} is no longer PENDING")
                self._pending.pop(request_id, None)
                self._emit("approval.expired", {"request_id": request_id})
                raise ValueError(f"Approval request {request_id} has expired")

            requester = req.requested_by or requester_id
            if prevent_self_approval and approver_id and approver_id == requester:
                return self.deny(
                    request_id,
                    approver_id=approver_id,
                    reason="Self-approval is not permitted",
                )

            # Build scope
            approval_scope = ApprovalScope(
                proposal_hash=req.proposal_hash,
                max_uses=1 if scope == "once" else 0,
                valid_until=req.expires_at,
            )

            response = ApprovalResponse(
                request_id=request_id,
                proposal_hash=req.proposal_hash,
                decision="APPROVED",
                scope=approval_scope,
                approver_id=approver_id,
                approver_method="broker",
                reason=reason,
            )
            lease = AuthorizationLease(
                proposal_hash=req.proposal_hash,
                approval_id=response.response_id,
                subject_id=req.requested_by,
                scope=approval_scope,
                max_uses=1,
                remaining_uses=1,
                expires_at=req.expires_at,
            )

            if not self._store.resolve_approval(
                request_id,
                expected_status=ApprovalStatus.PENDING.value,
                new_status=ApprovalStatus.APPROVED.value,
                response_dict=response.to_dict(),
                lease_dict=lease.to_dict(),
            ):
                raise ValueError(f"Approval request {request_id} is no longer PENDING")
            self._pending.pop(request_id, None)

        self._emit("approval.granted", {
            "request_id": request_id,
            "approver_id": approver_id,
            "scope": scope,
            "reason": reason,
        })

        _log.info("Approval granted: %s by %s", request_id, approver_id)
        return response

    def deny(
        self,
        request_id: str,
        *,
        approver_id: str,
        reason: str = "",
    ) -> ApprovalResponse:
        """Deny a pending approval request."""
        with self._lock:
            req = self._pending.get(request_id)
            if not req:
                req_data = self._store.get_approval_request(request_id)
                if req_data:
                    req = ApprovalRequest.from_dict(req_data)
            if not req:
                raise ValueError(f"Approval request {request_id} not found")

            if req.status != ApprovalStatus.PENDING.value:
                raise ValueError(
                    f"Approval request {request_id} is not PENDING (status={req.status})"
                )

            response = ApprovalResponse(
                request_id=request_id,
                proposal_hash=req.proposal_hash,
                decision="DENIED",
                approver_id=approver_id,
                approver_method="broker",
                reason=reason,
            )

            if not self._store.resolve_approval(
                request_id,
                expected_status=ApprovalStatus.PENDING.value,
                new_status=ApprovalStatus.DENIED.value,
                response_dict=response.to_dict(),
            ):
                raise ValueError(f"Approval request {request_id} is no longer PENDING")
            self._pending.pop(request_id, None)

        self._emit("approval.denied", {
            "request_id": request_id,
            "approver_id": approver_id,
            "reason": reason,
        })

        _log.info("Approval denied: %s by %s", request_id, approver_id)
        return response

    def get_pending(self) -> list[dict[str, Any]]:
        """List all pending approval requests."""
        return self._store.list_pending_approvals()

    def get_pending_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """List pending approvals for a specific run."""
        all_pending = self._store.list_pending_approvals()
        return [a for a in all_pending if a.get("run_id") == run_id]

    def expire_old(self) -> int:
        """Expire approvals past their expiration time. Returns count expired."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expired_count = 0
        with self._lock:
            to_remove = []
            for rid, req in list(self._pending.items()):
                if req.expires_at and req.expires_at <= now:
                    self._store.update_approval_status(rid, "EXPIRED")
                    to_remove.append(rid)
                    expired_count += 1
            for rid in to_remove:
                del self._pending[rid]
        return expired_count

    def set_policy(self, policy: ApprovalPolicy) -> None:
        """Set an approval policy for an agent or capability."""
        with self._lock:
            key = f"{policy.agent_id}:{policy.capability_id}"
            self._policies[key] = policy
            self._store.save_approval_policy(policy.to_dict())

    def get_policy(self, agent_id: str, capability_id: str = "") -> ApprovalPolicy | None:
        """Get the approval policy for an agent/capability."""
        with self._lock:
            key = f"{agent_id}:{capability_id}"
            return self._policies.get(key)

    def should_auto_approve(
        self,
        agent_id: str,
        capability_id: str,
        risk_level: str,
        is_read_only: bool,
        is_test: bool,
    ) -> bool:
        """Check if the action should be auto-approved based on policy."""
        policy = self.get_policy(agent_id, capability_id)
        if policy is None:
            policy = self.get_policy(agent_id, "")  # agent-level fallback
        if policy is None:
            return False
        return policy.evaluate(risk_level, is_read_only, is_test) == "allow"


# Module-level singleton
_broker: ApprovalBroker | None = None
_broker_lock = threading.Lock()


def get_broker(store: GovernanceStore | None = None) -> ApprovalBroker:
    global _broker
    if _broker is None:
        with _broker_lock:
            if _broker is None:
                _broker = ApprovalBroker(store=store)
    return _broker
