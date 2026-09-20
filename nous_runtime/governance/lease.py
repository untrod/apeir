# -*- coding: utf-8 -*-
"""Authorization lease manager — issuance, consumption, revocation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalResponse,
    ApprovalScope,
    AuthorizationLease,
    RevocationRecord,
    _new_id,
)
from nous_runtime.governance.store import GovernanceStore

_log = logging.getLogger("nous.governance.lease")


class LeaseManager:
    """Manages authorization lease lifecycle."""

    def __init__(self, store: GovernanceStore | None = None):
        self.store = store or GovernanceStore()

    def issue(
        self,
        proposal: ActionProposal,
        response: ApprovalResponse,
        *,
        subject_id: str = "",
        max_uses: int = 1,
        validity_hours: int = 1,
    ) -> AuthorizationLease:
        """Issue a lease after approval."""
        expires = (datetime.now(timezone.utc) + timedelta(hours=validity_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        scope = response.scope or ApprovalScope.from_proposal(proposal)
        lease = AuthorizationLease(
            lease_id=_new_id("al"),
            proposal_hash=proposal.proposal_hash,
            approval_id=response.response_id,
            subject_id=subject_id or response.approver_id,
            scope=scope,
            max_uses=max_uses,
            remaining_uses=max_uses,
            expires_at=expires,
            status="ACTIVE",
        )
        self.store.save_lease(lease.to_dict())
        _log.info("Lease issued: %s for proposal %s (uses=%d, expires=%s)",
                  lease.lease_id, proposal.proposal_hash[:12], max_uses, expires)
        return lease

    def consume(self, lease_id: str, execution_id: str) -> tuple[bool, int]:
        """Atomically consume one lease use. Returns (success, remaining_after)."""
        ok, remaining = self.store.consume_lease(lease_id, execution_id)
        if ok:
            _log.info("Lease %s consumed (execution=%s, remaining=%d)",
                      lease_id, execution_id, remaining)
        return ok, remaining

    def revoke(
        self,
        lease_id: str,
        revoked_by: str,
        *,
        reason: str = "",
    ) -> RevocationRecord:
        """Revoke an active lease."""
        lease = self.store.get_lease(lease_id)
        if not lease:
            raise ValueError(f"Lease {lease_id} not found")

        self.store.update_lease_status(lease_id, "REVOKED")
        revocation = RevocationRecord(
            target_type="lease",
            target_id=lease_id,
            revoked_by=revoked_by,
            reason=reason,
        )
        self.store.save_revocation(revocation.to_dict())
        _log.info("Lease %s revoked by %s: %s", lease_id, revoked_by, reason)
        return revocation

    def get_lease(self, lease_id: str) -> dict[str, Any] | None:
        """Get a lease by ID."""
        return self.store.get_lease(lease_id)

    def list_active(self, subject_id: str = "") -> list[dict[str, Any]]:
        """List active leases."""
        return self.store.list_active_leases(subject_id)
