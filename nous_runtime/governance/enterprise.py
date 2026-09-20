"""Enterprise organization, RBAC, workspace, and policy interfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
    AuthorizationEvidenceBundle,
)
from nous_runtime.governance.gate import get_gate
from nous_runtime.governance.store import GovernanceStore

POLICY_VERSION = "enterprise-alpha-1"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"runtime.read", "workspace.read"}),
    "operator": frozenset({"runtime.read", "workspace.read", "runtime.execute"}),
    "developer": frozenset(
        {
            "runtime.read",
            "workspace.read",
            "workspace.write",
            "runtime.execute",
            "capability.execute",
        }
    ),
    "approver": frozenset({"runtime.read", "approval.decide", "audit.read"}),
    "auditor": frozenset({"runtime.read", "workspace.read", "audit.read"}),
    "admin": frozenset(
        {
            "runtime.read",
            "workspace.read",
            "workspace.write",
            "runtime.execute",
            "capability.execute",
            "approval.decide",
            "audit.read",
            "policy.manage",
            "organization.manage",
        }
    ),
}


@dataclass(frozen=True)
class OrganizationMembership:
    organization_id: str
    subject_id: str
    roles: tuple[str, ...]
    workspace_ids: tuple[str, ...]
    additional_permissions: tuple[str, ...] = ()
    active: bool = True

    def __post_init__(self) -> None:
        if not self.organization_id or not self.subject_id:
            raise ValueError("organization_id and subject_id are required")
        unknown = set(self.roles) - set(ROLE_PERMISSIONS)
        if unknown:
            raise ValueError("unknown enterprise roles: " + ", ".join(sorted(unknown)))

    @property
    def permissions(self) -> frozenset[str]:
        permissions = set(self.additional_permissions)
        for role in self.roles:
            permissions.update(ROLE_PERMISSIONS[role])
        return frozenset(permissions)


@dataclass(frozen=True)
class EnterpriseAuthorization:
    allowed: bool
    requires_approval: bool
    reason_code: str
    organization_id: str = ""
    workspace_id: str = ""
    governance_decision: dict[str, Any] | None = None
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MembershipResolver = Callable[[str], OrganizationMembership | None]


class EnterprisePolicyInterface:
    """Fail-closed pre-authorization followed by the existing Governance Gate."""

    def __init__(
        self,
        membership_resolver: MembershipResolver,
        *,
        gate: Any = None,
        store: GovernanceStore | None = None,
    ) -> None:
        self.membership_resolver = membership_resolver
        self.gate = gate or get_gate()
        self.store = store or GovernanceStore()

    def evaluate(
        self,
        proposal: ActionProposal,
        context: AuthorizationContext,
    ) -> EnterpriseAuthorization:
        membership = self.membership_resolver(context.subject_id)
        precheck = self._precheck(proposal, context, membership)
        if not self._audit(precheck, proposal, context, membership):
            return EnterpriseAuthorization(
                False,
                False,
                "ENTERPRISE_AUDIT_UNAVAILABLE",
                membership.organization_id if membership else "",
                proposal.target_workspace,
            )
        if not precheck.allowed:
            return precheck
        decision = self.gate.evaluate(proposal, context)
        mode = str(decision.action_mode)
        return EnterpriseAuthorization(
            mode == "EXECUTE",
            precheck.requires_approval or mode == "ASK_APPROVAL",
            str(decision.reason_code or mode),
            membership.organization_id if membership else "",
            proposal.target_workspace,
            decision.to_dict(),
        )

    def describe_policy(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "policy_version": POLICY_VERSION,
            "default": "deny",
            "roles": {
                role: sorted(permissions)
                for role, permissions in sorted(ROLE_PERMISSIONS.items())
            },
            "workspace_scope_required_for_writes": True,
            "approval_authority": "ApprovalBroker",
            "execution_authority": "ExecutionAuthorizationGate",
        }

    @staticmethod
    def _precheck(
        proposal: ActionProposal,
        context: AuthorizationContext,
        membership: OrganizationMembership | None,
    ) -> EnterpriseAuthorization:
        organization_id = membership.organization_id if membership else ""
        workspace_id = proposal.target_workspace
        if (
            membership is None
            or not membership.active
            or not context.subject_id
            or membership.subject_id != context.subject_id
        ):
            return EnterpriseAuthorization(
                False, False, "ENTERPRISE_MEMBERSHIP_DENIED", organization_id, workspace_id
            )
        minimum_confidence = 0.7 if context.session_locality == "remote" else 0.5
        if context.authn_confidence < minimum_confidence:
            return EnterpriseAuthorization(
                False, False, "ENTERPRISE_AUTHN_INSUFFICIENT", organization_id, workspace_id
            )
        if workspace_id and workspace_id not in membership.workspace_ids and "*" not in membership.workspace_ids:
            return EnterpriseAuthorization(
                False, False, "ENTERPRISE_WORKSPACE_DENIED", organization_id, workspace_id
            )
        required = EnterprisePolicyInterface._required_permission(proposal)
        if required in {"workspace.write", "runtime.execute"} and not workspace_id:
            return EnterpriseAuthorization(
                False, False, "ENTERPRISE_WORKSPACE_REQUIRED", organization_id, workspace_id
            )
        required_permissions = {required, *proposal.required_permissions}
        if proposal.capability_id:
            required_permissions.add("capability.execute")
        if not required_permissions.issubset(membership.permissions):
            return EnterpriseAuthorization(
                False, False, "ENTERPRISE_RBAC_DENIED", organization_id, workspace_id
            )
        approval_required = proposal.side_effect_class in {"external_write", "destructive"}
        return EnterpriseAuthorization(
            True, approval_required, "ENTERPRISE_PREAUTHORIZED", organization_id, workspace_id
        )

    @staticmethod
    def _required_permission(proposal: ActionProposal) -> str:
        if proposal.action_type.startswith("approval."):
            return "approval.decide"
        if proposal.action_type.startswith("audit."):
            return "audit.read"
        if proposal.action_type.startswith("policy."):
            return "policy.manage"
        if proposal.side_effect_class in {"local_write"}:
            return "workspace.write"
        if proposal.side_effect_class in {"external_write", "destructive"}:
            return "runtime.execute"
        return "runtime.read"

    def _audit(
        self,
        result: EnterpriseAuthorization,
        proposal: ActionProposal,
        context: AuthorizationContext,
        membership: OrganizationMembership | None,
    ) -> bool:
        evidence = AuthorizationEvidenceBundle(
            proposal_hash=proposal.proposal_hash,
            event_type="enterprise_pre_authorization",
            evidence={
                "allowed": result.allowed,
                "requires_approval": result.requires_approval,
                "reason_code": result.reason_code,
                "organization_id": membership.organization_id if membership else "",
                "roles": sorted(membership.roles) if membership else [],
                "subject_id": context.subject_id,
                "workspace_id": proposal.target_workspace,
                "policy_version": POLICY_VERSION,
            },
        )
        return bool(self.store.save_audit(evidence.to_dict()))
