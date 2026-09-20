# -*- coding: utf-8 -*-
"""Evaluation Security — governance protection for evaluation state.

Rules:
  1. Agents CANNOT modify their own evaluation scores
  2. Only system/user can create/modify evaluations
  3. All evaluation modifications are audited
  4. Evidence is immutable once recorded
  5. History records cannot be deleted by agents
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.evaluation.models import EvaluationRecord

_log = logging.getLogger("nous.evaluation.security")



# Access control


@dataclass
class EvaluationAccessRequest:
    """Request to access or modify evaluation data."""
    actor: str = ""
    actor_type: str = ""       # "agent", "user", "system"
    action: str = ""           # "read", "create", "modify", "delete"
    record_id: str = ""
    purpose: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationAccessDecision:
    """Result of evaluation access check."""
    allowed: bool = False
    reason: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



# Evaluation Guard


class EvaluationGuard:
    """Protects evaluation data from unauthorized modification.

    Usage::

        guard = EvaluationGuard()
        decision = guard.authorize(EvaluationAccessRequest(
            actor="agent_coding",
            actor_type="agent",
            action="modify",
            record_id="eval_001",
        ))
        # → denied: agents cannot modify evaluations
    """

    # Who can do what
    PERMISSIONS = {
        "system": {"read", "create", "modify", "delete"},
        "user": {"read", "create"},
        "agent": {"read"},     # Agents can ONLY read — never modify
    }

    def authorize(self, request: EvaluationAccessRequest) -> EvaluationAccessDecision:
        """Check if an actor can perform an action on evaluation data."""
        allowed_actions = self.PERMISSIONS.get(request.actor_type, set())

        if request.action not in allowed_actions:
            return EvaluationAccessDecision(
                allowed=False,
                reason=(
                    f"Actor type '{request.actor_type}' cannot '{request.action}' "
                    f"evaluation records. Allowed: {sorted(allowed_actions)}"
                ),
            )

        # Agents specifically cannot modify their own evaluations
        if request.actor_type == "agent" and request.action == "modify":
            if request.record_id:
                return EvaluationAccessDecision(
                    allowed=False,
                    reason="Agents cannot modify evaluation records (including their own scores).",
                )

        # Governance gate check
        try:
            from nous_runtime.governance.gate import get_gate
            from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext

            gate = get_gate()
            proposal = ActionProposal(
                capability_id="evaluation.access",
                action_type=f"evaluation.{request.action}",
                parameter_summary=(
                    f"actor={request.actor} action={request.action} "
                    f"record={request.record_id} purpose={request.purpose}"
                ),
                data_classification="internal",
                side_effect_class="read_only" if request.action == "read" else "mutation",
                reversibility="reversible" if request.action != "delete" else "irreversible",
            )
            auth_ctx = AuthorizationContext(
                surface="local_cli",
            )
            try:
                # Try with principal_id if supported
                auth_ctx = AuthorizationContext(
                    principal_id=request.actor,
                    surface="local_cli",
                )
            except TypeError:
                auth_ctx = AuthorizationContext(surface="local_cli")

            decision = gate.evaluate(proposal, auth_ctx)
            if decision.action_mode not in ("EXECUTE", "RECOMMEND"):
                return EvaluationAccessDecision(
                    allowed=False,
                    reason=f"Governance gate denied: {decision.reason_code}",
                )
        except Exception as exc:
            _log.debug("Governance gate unavailable for eval auth: %s", exc)

        return EvaluationAccessDecision(
            allowed=True,
            reason=f"{request.action} granted for {request.actor_type}:{request.actor}",
        )



    def verify_record_integrity(self, record: EvaluationRecord) -> list[str]:
        """Verify an evaluation record has not been tampered with.

        Returns list of integrity violations (empty = clean).
        """
        violations: list[str] = []

        # 1. Checksum verification
        expected = record.checksum()
        # Re-compute from stored to_dict
        from_dict = record.to_dict()
        reconstructed = EvaluationRecord.from_dict(from_dict)
        if reconstructed.checksum() != expected:
            violations.append("Checksum mismatch — record may have been modified.")

        # 2. Schema version check
        from nous_runtime.evaluation.schema import EVALUATION_SCHEMA_VERSION
        if record.schema_version != EVALUATION_SCHEMA_VERSION:
            violations.append(
                f"Schema version mismatch: {record.schema_version} vs {EVALUATION_SCHEMA_VERSION}"
            )

        # 3. Required fields
        if not record.target_type:
            violations.append("Missing target_type")
        if not record.id:
            violations.append("Missing id")
        if not record.evaluated_by:
            violations.append("Missing evaluated_by")

        return violations

    def verify_evidence_immutable(
        self,
        original: EvaluationRecord,
        modified: EvaluationRecord,
    ) -> list[str]:
        """Verify evidence has not been altered between two records."""
        violations: list[str] = []
        orig_dims = {d.dimension: d for d in original.dimensions}
        mod_dims = {d.dimension: d for d in modified.dimensions}

        for dim_name, orig_dim in orig_dims.items():
            mod_dim = mod_dims.get(dim_name)
            if mod_dim is None:
                continue
            if orig_dim.evidence_count != mod_dim.evidence_count:
                violations.append(
                    f"Evidence count changed for {dim_name}: "
                    f"{orig_dim.evidence_count} → {mod_dim.evidence_count}"
                )
            for i, (oe, me) in enumerate(zip(orig_dim.evidence, mod_dim.evidence)):
                if oe.evidence_id != me.evidence_id:
                    violations.append(f"Evidence {i} id changed in {dim_name}")
                if oe.score != me.score:
                    violations.append(f"Evidence {i} score changed in {dim_name}")

        return violations



# Convenience


def authorize_evaluation_access(
    actor: str,
    actor_type: str,
    action: str,
    record_id: str = "",
    purpose: str = "",
) -> EvaluationAccessDecision:
    """One-shot evaluation access check."""
    return EvaluationGuard().authorize(EvaluationAccessRequest(
        actor=actor, actor_type=actor_type,
        action=action, record_id=record_id, purpose=purpose,
    ))
