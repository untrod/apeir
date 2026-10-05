"""Operation projections of the existing governance and lease contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.governance.broker import ApprovalPolicy
from nous_runtime.governance.contracts import AuthorizationLease

# The existing human-owned approval policy remains the policy authority.
Policy = ApprovalPolicy


class GovernanceDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    UNKNOWN = "UNKNOWN"


class GrantScope(str, Enum):
    ONCE = "ONCE"
    WORK = "WORK"
    SESSION = "SESSION"
    RESOURCE = "RESOURCE"
    CAPABILITY = "CAPABILITY"


@dataclass(frozen=True)
class GovernanceRequest:
    operation_id: str
    work_id: str
    capability_id: str
    resource_id: str
    subject_id: str
    agent_session_id: str = ""
    workflow_run_id: str = ""
    plan_id: str = ""
    node_id: str = ""
    input_artifacts: tuple[str, ...] = ()
    expected_effect: dict[str, Any] = field(default_factory=dict)
    capability_inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["input_artifacts"] = list(self.input_artifacts)
        return value

    @property
    def authorization_id(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "gov_" + hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GovernanceRequest:
        return cls(
            **{**value, "input_artifacts": tuple(value.get("input_artifacts", ()))}
        )


@dataclass(frozen=True)
class CapabilityGrant(AuthorizationLease):
    """A scoped Capability 2.0 projection of a durable authorization lease."""

    scope_kind: str = GrantScope.ONCE.value
    capability_id: str = ""
    resource_id: str = ""
    work_id: str = ""
    agent_session_id: str = ""
    node_id: str = ""
    authorized_by: str = ""
    operation_governance: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            **{
                key: getattr(self, key)
                for key in (
                    "scope_kind",
                    "capability_id",
                    "resource_id",
                    "work_id",
                    "agent_session_id",
                    "node_id",
                    "authorized_by",
                    "operation_governance",
                )
            },
        }


class GovernanceApprovalRequired(ValueError):
    """A durable handler pause consumed by WorkflowRuntime."""

    def __init__(self, output: dict[str, Any]):
        super().__init__("Operation requires human approval")
        self.workflow_output = output
