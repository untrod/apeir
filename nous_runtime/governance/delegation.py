# -*- coding: utf-8 -*-
"""Delegation manager — grant creation, validation, consumption."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalScope,
    DelegationConstraint,
    DelegationGrant,
    RevocationRecord,
    _new_id,
)
from nous_runtime.governance.store import GovernanceStore

_log = logging.getLogger("nous.governance.delegation")


class DelegationManager:
    """Manages delegation grant lifecycle."""

    def __init__(self, store: GovernanceStore | None = None):
        self.store = store or GovernanceStore()

    def create_grant(
        self,
        issuer_id: str,
        subject_id: str,
        scope: ApprovalScope,
        *,
        permitted_capabilities: tuple[str, ...] = (),
        denied_capabilities: tuple[str, ...] = (),
        constraints: tuple[DelegationConstraint, ...] = (),
        max_uses: int = 1,
        validity_hours: int = 168,  # 7 days default
        allow_sub_delegation: bool = False,
    ) -> DelegationGrant:
        """Create a new delegation grant."""
        expires = (datetime.now(timezone.utc) + timedelta(hours=validity_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        grant = DelegationGrant(
            grant_id=_new_id("dg"),
            issuer_id=issuer_id,
            subject_id=subject_id,
            scope=scope,
            permitted_capabilities=permitted_capabilities,
            denied_capabilities=denied_capabilities,
            constraints=constraints,
            max_uses=max_uses,
            expires_at=expires,
            allow_sub_delegation=allow_sub_delegation,
            status="ACTIVE",
        )
        self.store.save_delegation(grant.to_dict())
        _log.info("Delegation grant created: %s issuer=%s -> subject=%s",
                  grant.grant_id, issuer_id, subject_id)
        return grant

    def validate_for_proposal(
        self,
        grant_id: str,
        proposal: ActionProposal,
    ) -> bool:
        """Check if an active delegation covers this proposal."""
        grant_dict = self.store.get_delegation(grant_id)
        if not grant_dict:
            return False
        if grant_dict["status"] != "ACTIVE":
            return False
        if grant_dict["used_count"] >= grant_dict.get("max_uses", 0):
            return False

        # Check expiration
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if grant_dict.get("expires_at", "") < now:
            self.store.update_delegation_status(grant_id, "EXPIRED")
            return False

        # Check denied capabilities
        denied = set(grant_dict.get("denied_capabilities", []))
        if proposal.capability_id in denied:
            return False

        # Check permitted capabilities
        permitted = set(grant_dict.get("permitted_capabilities", []))
        if "*" not in permitted and proposal.capability_id not in permitted:
            return False

        scope_dict = grant_dict.get("scope")
        if scope_dict:
            approved_scope = ApprovalScope.from_dict(scope_dict)
            if approved_scope.capability_id and approved_scope.capability_id != proposal.capability_id:
                return False
            if approved_scope.allowed_capabilities and proposal.capability_id not in approved_scope.allowed_capabilities:
                return False
            if approved_scope.workspace_path:
                proposal_scope = ApprovalScope.from_proposal(proposal)
                if not ApprovalScope(workspace_path=proposal_scope.workspace_path).is_subset_of(
                    ApprovalScope(workspace_path=approved_scope.workspace_path)
                ):
                    return False
            if approved_scope.allowed_files:
                allowed = set(approved_scope.allowed_files)
                if not all(resource in allowed for resource in proposal.affected_resources):
                    return False
            if approved_scope.cost_ceiling_usd and proposal.estimated_cost_usd > approved_scope.cost_ceiling_usd:
                return False
            if approved_scope.allowed_side_effect_classes:
                if proposal.side_effect_class not in approved_scope.allowed_side_effect_classes:
                    return False

        # Check constraints
        for c_dict in grant_dict.get("constraints", []):
            c = DelegationConstraint.from_dict(c_dict)
            if c.constraint_type == "cost" and proposal.estimated_cost_usd:
                if c.operator == "lte" and proposal.estimated_cost_usd > float(c.value or 0):
                    return False

        return True

    def revoke(
        self,
        grant_id: str,
        revoked_by: str,
        *,
        reason: str = "",
    ) -> RevocationRecord:
        """Revoke an active delegation."""
        grant = self.store.get_delegation(grant_id)
        if not grant:
            raise ValueError(f"Delegation {grant_id} not found")

        self.store.update_delegation_status(grant_id, "REVOKED")
        revocation = RevocationRecord(
            target_type="delegation",
            target_id=grant_id,
            revoked_by=revoked_by,
            reason=reason,
        )
        self.store.save_revocation(revocation.to_dict())
        _log.info("Delegation %s revoked by %s: %s", grant_id, revoked_by, reason)
        return revocation

    def get_grant(self, grant_id: str) -> dict[str, Any] | None:
        """Get a delegation grant by ID."""
        return self.store.get_delegation(grant_id)

    def list_active(self, subject_id: str = "") -> list[dict[str, Any]]:
        """List active delegation grants."""
        return self.store.list_active_delegations(subject_id)
