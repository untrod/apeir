# -*- coding: utf-8 -*-
"""
Nous Runtime Governance — B1 authorization foundation.

Public API:
  - get_gate() — singleton ExecutionAuthorizationGate
  - get_store() — singleton GovernanceStore
  - All canonical contracts (AuthorizationContext, ActionProposal, etc.)
  - ApprovalManager, LeaseManager, DelegationManager

EffectGate projects execution-proof concepts into the Python distribution. It
does not replace Kernel authorization or proof authority.
"""

# Effect Gate exports
from nous_runtime.governance.effect_gate import (
    ApprovalBinding,
    CanonicalAction,
    EffectGate,
    EffectReceipt,
    EffectStatus,
    GateDecision,
)

from threading import Lock

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalScope,
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationEvidenceBundle,
    AuthorizationLease,
    DelegationConstraint,
    DelegationGrant,
    EscalationRecord,
    RevocationRecord,
    RiskAssessment,
    RiskEnvelope,
)
from nous_runtime.governance.gate import ExecutionAuthorizationGate, get_gate
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.governance.enterprise import (
    EnterprisePolicyInterface,
    OrganizationMembership,
)
from nous_runtime.governance.approval import ApprovalManager
from nous_runtime.governance.lease import LeaseManager
from nous_runtime.governance.delegation import DelegationManager
from nous_runtime.governance.permission import (
    PermissionDecision,
    PermissionEngine,
    PermissionRequest,
    PermissionRule,
)
from nous_runtime.governance.runtime_mode import (
    GovernanceRuntimeMode,
    mode_policy,
    resolve_runtime_mode,
    should_fail_closed,
)

_store_instance: GovernanceStore | None = None
_store_lock = Lock()


def get_store() -> GovernanceStore:
    """Return the process-wide governance store used by CLI facades."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = GovernanceStore()
    return _store_instance


__all__ = [
    "ApprovalBinding",
    "CanonicalAction",
    "EffectGate",
    "EffectReceipt",
    "EffectStatus",
    "GateDecision",
    # Gate
    "ExecutionAuthorizationGate",
    "get_gate",
    # Store
    "GovernanceStore",
    "get_store",
    # Contracts
    "ActionProposal",
    "AuthorizationContext",
    "AuthorizationDecision",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalScope",
    "AuthorizationLease",
    "DelegationGrant",
    "DelegationConstraint",
    "RevocationRecord",
    "EscalationRecord",
    "RiskEnvelope",
    "RiskAssessment",
    "AuthorizationEvidenceBundle",
    "EnterprisePolicyInterface",
    "OrganizationMembership",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionRequest",
    "PermissionRule",
    # Managers
    "ApprovalManager",
    "LeaseManager",
    "DelegationManager",
    "GovernanceRuntimeMode",
    "mode_policy",
    "resolve_runtime_mode",
    "should_fail_closed",
]
