# -*- coding: utf-8 -*-
"""Approval lifecycle manager."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalScope,
    AuthorizationContext,
    _new_id,
)
from nous_runtime.governance.store import GovernanceStore

_log = logging.getLogger("nous.governance.approval")


class ApprovalManager:
    """Manages the approval request/response lifecycle."""

    def __init__(self, store: GovernanceStore | None = None):
        self.store = store or GovernanceStore()

    def create_request(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
        *,
        risk_summary: str = "",
        expires_in_hours: int = 24,
    ) -> ApprovalRequest:
        """Create an approval request from a proposal."""
        expires = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        request = ApprovalRequest(
            request_id=_new_id("apr"),
            proposal_hash=proposal.proposal_hash,
            summary=f"{proposal.action_type}: {proposal.capability_id}",
            risk_summary=risk_summary or proposal.side_effect_class,
            scope_summary=f"Workspace: {proposal.target_workspace}, "
                          f"Resources: {len(proposal.affected_resources)}, "
                          f"Cost: ${proposal.estimated_cost_usd:.4f}",
            status="PENDING",
            requested_by=context.subject_id,
            expires_at=expires,
        )
        self.store.save_approval_request(request.to_dict())
        _log.info("Approval request created: %s for %s", request.request_id, proposal.capability_id)
        return request

    def approve(
        self,
        request_id: str,
        approver_id: str,
        scope: ApprovalScope | None = None,
        *,
        reason: str = "",
    ) -> ApprovalResponse:
        """Approve a pending approval request."""
        req = self.store.get_approval_request(request_id)
        if not req:
            raise ValueError(f"Approval request {request_id} not found")
        if req["status"] != "PENDING":
            raise ValueError(f"Approval request {request_id} is not PENDING (status={req['status']})")

        response = ApprovalResponse(
            request_id=request_id,
            proposal_hash=req["proposal_hash"],
            decision="APPROVED",
            scope=scope,
            approver_id=approver_id,
            approver_method="cli",
            reason=reason,
        )
        if not self.store.resolve_approval(
            request_id,
            expected_status="PENDING",
            new_status="APPROVED",
            response_dict=response.to_dict(),
        ):
            raise ValueError(f"Approval request {request_id} is no longer PENDING")
        _log.info("Approval %s approved by %s", request_id, approver_id)
        return response

    def deny(
        self,
        request_id: str,
        approver_id: str,
        *,
        reason: str = "",
    ) -> ApprovalResponse:
        """Deny a pending approval request."""
        req = self.store.get_approval_request(request_id)
        if not req:
            raise ValueError(f"Approval request {request_id} not found")
        if req["status"] != "PENDING":
            raise ValueError(f"Approval request {request_id} is not PENDING (status={req['status']})")

        response = ApprovalResponse(
            request_id=request_id,
            proposal_hash=req["proposal_hash"],
            decision="DENIED",
            approver_id=approver_id,
            approver_method="cli",
            reason=reason,
        )
        if not self.store.resolve_approval(
            request_id,
            expected_status="PENDING",
            new_status="DENIED",
            response_dict=response.to_dict(),
        ):
            raise ValueError(f"Approval request {request_id} is no longer PENDING")
        _log.info("Approval %s denied by %s", request_id, approver_id)
        return response

    def get_pending(self, subject_id: str = "") -> list[dict[str, Any]]:
        """List pending approval requests."""
        return self.store.list_pending_approvals(subject_id)

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Get an approval request by ID."""
        return self.store.get_approval_request(request_id)

    def validate_scope_modification(
        self,
        proposed: ApprovalScope,
        modified: ApprovalScope,
    ) -> bool:
        """Returns True if modified scope is a valid reduction of proposed."""
        return modified.is_subset_of(proposed)
