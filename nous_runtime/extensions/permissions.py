"""Capability diffing and approval-bound Kernel authorization for extensions."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.extensions.admission import (
    AdmissionDecision,
    ExtensionAdmissionError,
    ExtensionAdmissionService,
)
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.broker import ApprovalBroker, ApprovalEvidence
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext


@dataclass(frozen=True)
class PermissionDiff:
    requested: tuple[str, ...]
    previously_granted: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]

    @property
    def approval_required(self) -> bool:
        return bool(self.added)

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": list(self.requested),
            "previously_granted": list(self.previously_granted),
            "added": list(self.added),
            "removed": list(self.removed),
            "unchanged": list(self.unchanged),
            "approval_required": self.approval_required,
        }


class ExtensionPermissionService:
    """Reuse ApprovalBroker and bind each approval to digest + capability diff."""

    REQUESTER = "nous.extension-manager"

    def __init__(
        self,
        registry: ExtensionRegistry,
        admission: ExtensionAdmissionService,
        broker: ApprovalBroker,
    ):
        self.registry = registry
        self.admission = admission
        self.broker = broker

    def diff(self, extension_id: str) -> PermissionDiff:
        manifest = self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id)
        if record is None:
            raise ExtensionAdmissionError("extension is not installed")
        requested = {item.capability for item in manifest.capabilities}
        current = set(record.get("granted_capabilities") or ())
        previous = set(record.get("previous_granted_capabilities") or ())
        baseline = current or previous
        return PermissionDiff(
            requested=tuple(sorted(requested)),
            previously_granted=tuple(sorted(baseline)),
            added=tuple(sorted(requested - baseline)),
            removed=tuple(sorted(baseline - requested)),
            unchanged=tuple(sorted(requested & baseline)),
        )

    def request(
        self,
        extension_id: str,
        context: AuthorizationContext,
    ):
        diff = self.diff(extension_id)
        if not diff.approval_required:
            return diff, None
        record = self.registry.get_record(extension_id)
        assert record is not None
        proposal = ActionProposal(
            action_type="extension.capabilities.approve",
            capability_id="extension.authorize",
            agent_id=self.REQUESTER,
            params={
                "extension_id": extension_id,
                "digest": record["digest"],
                "capabilities": list(diff.added),
            },
            target_workspace=str(self.registry.root),
            affected_resources=(extension_id, str(record["digest"])),
            data_classification="internal",
            side_effect_class="local_write",
            reversibility="reversible",
            retry_behavior="safe_with_key",
            required_permissions=diff.added,
        )
        request = self.broker.request_approval(
            run_id=f"extension:{extension_id}",
            task_id="extension-permission-grant",
            proposal=proposal,
            context=context,
            evidence=ApprovalEvidence(
                workspace_path=str(self.registry.root),
                capability_request=", ".join(diff.added),
                risk_envelope={
                    "extension_id": extension_id,
                    "digest": record["digest"],
                    "added": list(diff.added),
                    "removed": list(diff.removed),
                },
            ),
            requester=self.REQUESTER,
        )
        self.registry.record_permission_request(
            extension_id,
            request_id=request.request_id,
            proposal_hash=proposal.proposal_hash,
            capabilities=diff.added,
        )
        return diff, request

    async def approve(
        self,
        extension_id: str,
        request_id: str,
        approver_id: str,
    ) -> AdmissionDecision:
        self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id)
        if record is None:
            raise ExtensionAdmissionError("extension is not installed")
        pending = record.get("pending_permission_request")
        if not isinstance(pending, dict) or pending.get("request_id") != request_id:
            raise ExtensionAdmissionError("permission request is not pending for extension")
        if pending.get("digest") != record.get("digest"):
            raise ExtensionAdmissionError("permission request digest is stale")
        approval_id = str(pending.get("approval_id") or "")
        if not approval_id:
            response = self.broker.approve(
                request_id,
                approver_id=approver_id,
                requester_id=self.REQUESTER,
                reason="Extension capability grant reviewed",
            )
            if response.decision != "APPROVED":
                self.registry.clear_permission_request(extension_id)
                raise ExtensionAdmissionError(
                    "extension permission request was not approved"
                )
            if response.proposal_hash != pending.get("proposal_hash"):
                raise ExtensionAdmissionError(
                    "approval does not match permission proposal"
                )
            approval_id = response.response_id
            self.registry.record_permission_approval(
                extension_id,
                request_id=request_id,
                proposal_hash=response.proposal_hash,
                approval_id=approval_id,
            )
        decision = await self.admission.authorize(
            extension_id,
            tuple(str(item) for item in pending.get("capabilities") or ()),
            approval_id,
        )
        self.registry.clear_permission_request(extension_id)
        return decision

    async def revoke(
        self, extension_id: str, *, reason: str = "user_requested"
    ) -> AdmissionDecision:
        return await self.admission.revoke(extension_id, reason=reason)
