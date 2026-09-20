# -*- coding: utf-8 -*-
"""Execution Authorization Gate -canonical enforcement point."""

from __future__ import annotations

import logging
import threading
from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationEvidenceBundle,
    _new_id,
)
from nous_runtime.governance.constitution import evaluate_constitution
from nous_runtime.governance.risk_engine import assess_risk
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.governance.runtime_mode import should_fail_closed
from nous_runtime.governance.permission import (
    PermissionEngine,
    PermissionRequest,
)

_log = logging.getLogger("nous.governance.gate")

_gate_instance: "ExecutionAuthorizationGate | None" = None
_gate_lock = threading.Lock()


def get_gate(store: GovernanceStore | None = None) -> "ExecutionAuthorizationGate":
    """Get or create the singleton ExecutionAuthorizationGate."""
    global _gate_instance
    if _gate_instance is None:
        with _gate_lock:
            if _gate_instance is None:
                _gate_instance = ExecutionAuthorizationGate(store=store)
    return _gate_instance


class ExecutionAuthorizationGate:
    """Single canonical enforcement point for all executable actions."""

    def __init__(
        self,
        store: GovernanceStore | None = None,
        *,
        permission_engine: PermissionEngine | None = None,
    ):
        self.store = store or GovernanceStore()
        self.permission_engine = permission_engine

    def evaluate(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
    ) -> AuthorizationDecision:
        """Evaluate whether the proposed action is authorized.

        Returns AuthorizationDecision with action_mode:
          EXECUTE, RECOMMEND, ASK_APPROVAL, ESCALATE, or DENY.
        """

        # Step 1: Validate proposal schema
        if not proposal.proposal_hash or not proposal.capability_id:
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "PROPOSAL_INVALID",
                    "Proposal is missing required fields",
                ),
                persist_proposal=False,
            )

        # Step 2: Validate proposal hash and expiration
        computed = proposal._compute_hash()
        if computed != proposal.proposal_hash:
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "PROPOSAL_TAMPERED",
                    "Proposal hash does not match computed hash",
                ),
            )

        if proposal.expires_at:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if proposal.expires_at < now:
                return self._finalize_decision(
                    proposal,
                    context,
                    self._deny(
                        proposal,
                        context,
                        "PROPOSAL_STALE",
                        "Proposal has expired",
                    ),
                )

        # Step 3: Enforce Runtime Constitution
        violations = evaluate_constitution(proposal, context)
        if violations:
            rule_ids = ", ".join(v.rule_id for v in violations)
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    f"CONSTITUTION_VIOLATION:{rule_ids}",
                    "; ".join(v.message for v in violations),
                    constitution_rule=rule_ids,
                ),
            )

        # Step 4: Validate subject identity
        if not context.subject_id:
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "IDENTITY_MISSING",
                    "No subject identity in authorization context",
                ),
            )

        if context.authn_confidence < 0.5:
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "IDENTITY_LOW_CONFIDENCE",
                    f"Authentication confidence too low: {context.authn_confidence}",
                ),
            )

        # Step 5: Validate session/device state
        # (placeholder -full session validation requires session registry integration)

        # Step 6: Validate capability registration
        capability = self._lookup_capability(proposal.capability_id)
        if capability is None:
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "CAPABILITY_UNKNOWN",
                    f"Capability '{proposal.capability_id}' is not registered",
                ),
            )

        if capability.get("disabled"):
            return self._finalize_decision(
                proposal,
                context,
                self._deny(
                    proposal,
                    context,
                    "CAPABILITY_DISABLED",
                    f"Capability '{proposal.capability_id}' is disabled",
                ),
            )

        # Step 7: Validate required permissions. Compatibility is preserved
        # when no permission engine is configured; configured deployments are
        # deny-by-default for every declared required permission.
        if proposal.required_permissions and self.permission_engine is not None:
            resources = proposal.affected_resources or (
                proposal.capability_id,
            )
            permission_context = {
                "subject_type": context.subject_type,
                "locality": context.session_locality,
                "device": context.session_device,
                "action_type": proposal.action_type,
            }
            for permission in proposal.required_permissions:
                for resource in resources:
                    permission_decision = self.permission_engine.check(
                        PermissionRequest(
                            subject=context.subject_id,
                            action=permission,
                            resource=resource,
                            context=permission_context,
                        )
                    )
                    if not permission_decision.allowed:
                        return self._finalize_decision(
                            proposal,
                            context,
                            self._deny(
                                proposal,
                                context,
                                "PERMISSION_DENIED",
                                (
                                    f"Permission '{permission}' denied for "
                                    f"resource '{resource}': "
                                    f"{permission_decision.reason}"
                                ),
                            ),
                        )

        # Step 8: Validate target resource scope
        if proposal.affected_resources:
            for resource in proposal.affected_resources:
                if ".." in resource:
                    return self._finalize_decision(
                        proposal,
                        context,
                        self._deny(
                            proposal,
                            context,
                            "RESOURCE_PATH_TRAVERSAL",
                            f"Path traversal detected in resource: {resource}",
                        ),
                    )

        # Step 9: Calculate RiskEnvelope
        risk_envelope = assess_risk(proposal, context, capability)

        # Step 10: Match active authorization lease
        lease = self.store.get_active_lease_for_proposal(
            proposal.proposal_hash, context.subject_id
        )
        lease_id = ""
        if lease:
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if lease.get("expires_at") and lease["expires_at"] < now:
                self.store.update_lease_status(lease["lease_id"], "EXPIRED")
            elif lease.get("remaining_uses", 0) > 0:
                execution_id = context.request_id or _new_id("exec")
                consumed, _remaining = self.store.consume_lease(
                    lease["lease_id"], execution_id
                )
                if consumed:
                    lease_id = lease["lease_id"]

        # Step 11: Match delegation grants (placeholder for delegation evaluation)

        # Step 12: Apply policy / risk thresholds
        action_mode = self._resolve_action_mode(
            risk_envelope, capability, bool(lease_id)
        )

        # Step 13: Build decision
        if action_mode == "EXECUTE":
            reason = (
                "Active lease covers this proposal"
                if lease_id
                else "Within autonomous authorization bounds"
            )
            decision = self._execute(
                proposal,
                context,
                risk_envelope,
                lease_id=lease_id,
                reason=reason,
            )
        elif action_mode == "ASK_APPROVAL":
            decision = self._ask_approval(proposal, context, risk_envelope)
        elif action_mode == "DENY":
            decision = self._deny(proposal, context, "POLICY_DENIED",
                                  "Policy evaluation resulted in denial")
        else:
            decision = self._escalate(proposal, context, risk_envelope,
                                      "Policy evaluation requires escalation")

        # Steps 14-16: persist proposal, decision, and audit evidence.
        return self._finalize_decision(proposal, context, decision)

    def _resolve_action_mode(
        self,
        risk: Any,
        capability: dict[str, Any] | None,
        has_lease: bool,
    ) -> str:
        """Determine action mode from risk envelope and capability manifest.

        H4 fix: A lease no longer fully bypasses governance. It REDUCES the risk
        by one level (e.g., high→medium, medium→low) but still requires the
        risk engine to run. Only SYSTEM-level leases (kernel internal) get EXECUTE.
        """
        # Kernel-level leases (nousd internal) bypass governance — trusted path
        lease_is_system = capability and capability.get("lease_level") == "system"

        if has_lease and lease_is_system:
            return "EXECUTE"

        aggregate = risk.aggregate_risk_class if risk else "medium"
        unknown_count = len(risk.unknown_dimensions) if risk else 0

        # A lease is the durable result of an explicit authorization decision.
        # The store atomically consumes its scoped use before this method runs.
        if has_lease:
            return "EXECUTE"

        # DENY: all dimensions unknown
        if unknown_count >= 5:
            return "DENY"

        # ESCALATE: 3+ unknown dimensions
        if unknown_count >= 3:
            return "ESCALATE"

        # ASK_APPROVAL: critical or high risk
        if aggregate == "critical":
            return "ASK_APPROVAL"
        if aggregate == "high":
            return "ASK_APPROVAL"

        # Capability manifest check
        if capability and capability.get("requires_approval"):
            if aggregate not in ("low",):
                return "ASK_APPROVAL"

        # EXECUTE: low or medium risk without approval requirements
        if aggregate in ("low", "medium"):
            if capability and capability.get("requires_approval"):
                return "ASK_APPROVAL"
            return "EXECUTE"

        # Default: ASK_APPROVAL
        return "ASK_APPROVAL"

    def _lookup_capability(self, capability_id: str) -> dict[str, Any] | None:
        """Look up a capability in the registry. Returns None if not found.

        v0.2.0: The hardcoded fallback allowlist is removed.  Every
        capability MUST be registered before execution.  Unregistered
        capabilities are treated as *unknown risk* and require approval.
        """
        try:
            from nous_runtime.compat.capability import get_capability
            cap = get_capability(capability_id)
            if cap:
                if isinstance(cap, dict):
                    normalized = dict(cap)
                    normalized["risk_level"] = cap.get(
                        "risk_level", cap.get("risk", "unknown")
                    )
                    normalized["requires_approval"] = bool(
                        cap.get("requires_approval", cap.get("requires_auth", False))
                    )
                    normalized["disabled"] = bool(
                        cap.get("disabled", not cap.get("enabled", True))
                    )
                    return normalized
                return {"name": str(cap)}
        except Exception:
            pass
        # v0.2.0: No hardcoded allowlist.  Unregistered capabilities are
        # treated as *unknown risk* — they require approval (ASK_APPROVAL)
        # but are NOT denied outright.  This maintains backward compatibility
        # with tests and runtime flows that create capabilities on-the-fly.
        return {
            "name": capability_id,
            "risk_level": "high",
            "requires_approval": True,
            "unregistered": True,
        }

    def _execute(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        risk: Any,
        *,
        lease_id: str = "",
        delegation_id: str = "",
        reason: str = "",
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            decision_id=_new_id("ad"),
            proposal_hash=proposal.proposal_hash,
            context_id=context.context_id,
            action_mode="EXECUTE",
            allowed=True,
            reason_code="AUTHORIZED",
            reason_message=reason,
            rule_class="AUTONOMOUS_ALLOWED",
            risk_envelope=risk if hasattr(risk, "to_dict") else None,
            lease_id=lease_id,
            delegation_id=delegation_id,
        )

    def _ask_approval(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        risk: Any,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            decision_id=_new_id("ad"),
            proposal_hash=proposal.proposal_hash,
            context_id=context.context_id,
            action_mode="ASK_APPROVAL",
            allowed=False,
            reason_code="APPROVAL_REQUIRED",
            reason_message=f"Risk class {risk.aggregate_risk_class if risk else 'unknown'} requires explicit approval",
            rule_class="USER_APPROVABLE",
            risk_envelope=risk if hasattr(risk, "to_dict") else None,
        )

    def _deny(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        reason_code: str,
        reason_message: str,
        *,
        constitution_rule: str = "",
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            decision_id=_new_id("ad"),
            proposal_hash=proposal.proposal_hash,
            context_id=context.context_id,
            action_mode="DENY",
            allowed=False,
            reason_code=reason_code,
            reason_message=reason_message,
            rule_class="NON_OVERRIDABLE" if "CONSTITUTION" in reason_code else "ADMIN_OVERRIDABLE",
            constitution_rule=constitution_rule,
        )

    def _escalate(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        risk: Any,
        reason: str,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            decision_id=_new_id("ad"),
            proposal_hash=proposal.proposal_hash,
            context_id=context.context_id,
            action_mode="ESCALATE",
            allowed=False,
            reason_code="ESCALATED",
            reason_message=reason,
            rule_class="ADMIN_OVERRIDABLE",
            risk_envelope=risk if hasattr(risk, "to_dict") else None,
        )

    def _store_unavailable(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        reason_code: str,
    ) -> AuthorizationDecision:
        if should_fail_closed(surface="server"):
            return self._deny(
                proposal,
                context,
                reason_code,
                "Governance persistence or audit store is unavailable",
            )
        _log.warning("Governance store unavailable in compatibility mode: %s", reason_code)
        return self._deny(proposal, context, reason_code, "Governance store unavailable")

    def _finalize_decision(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        decision: AuthorizationDecision,
        *,
        persist_proposal: bool = True,
    ) -> AuthorizationDecision:
        if persist_proposal and not self.store.save_proposal(proposal.to_dict()):
            return self._store_unavailable(
                proposal, context, "PROPOSAL_STORE_UNAVAILABLE"
            )
        if not self.store.save_decision(decision.to_dict()):
            return self._store_unavailable(
                proposal, context, "DECISION_STORE_UNAVAILABLE"
            )
        if not self._write_audit(decision, proposal, context):
            return self._store_unavailable(
                proposal, context, "AUDIT_STORE_UNAVAILABLE"
            )
        return decision

    def _write_audit(
        self,
        decision: AuthorizationDecision,
        proposal: ActionProposal,
        context: AuthorizationContext,
    ) -> bool:
        try:
            bundle = AuthorizationEvidenceBundle(
                decision_id=decision.decision_id,
                proposal_hash=proposal.proposal_hash,
                event_type="authorization_decision",
                evidence={
                    "action_mode": decision.action_mode,
                    "reason_code": decision.reason_code,
                    "capability_id": proposal.capability_id,
                    "subject_id": context.subject_id,
                    "subject_type": context.subject_type,
                },
            )
            return self.store.save_audit(bundle.to_dict())
        except Exception as e:
            _log.error("Failed to write audit evidence: %s", e)
            return False
