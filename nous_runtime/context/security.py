# -*- coding: utf-8 -*-
"""Context Security — Governance integration for context access.

All context reads by agents MUST be authorized through the Governance Gate.
All access MUST be audited (actor, context_id, purpose, timestamp, decision).

Rules:
  - Coding Agent: allowed Project, Code, Task context
  - Coding Agent: denied Private User Context
  - Every read must have a stated purpose
  - Every access decision must be recorded
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.context.models import ContextItem
from nous_runtime.context.store import ContextStore
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
    _new_id,
)

_log = logging.getLogger("nous.context.security")


# Access control model


@dataclass
class ContextAccessRequest:
    """A request to access context data."""

    actor: str = ""  # Agent ID, user ID, or system component
    actor_type: str = ""  # "agent", "user", "system"
    context_id: str = ""  # Snapshot ID or item ID
    purpose: str = ""  # Why context is needed
    requested_sources: tuple[str, ...] = ()  # Which ContextSources are requested
    metadata: dict[str, Any] = field(default_factory=dict)
    authorization_context: AuthorizationContext | None = field(default=None, repr=False)


@dataclass
class ContextAccessDecision:
    """Result of a context access authorization check."""

    allowed: bool = False
    reason: str = ""
    granted_sources: tuple[str, ...] = ()
    denied_sources: tuple[str, ...] = ()
    decision_id: str = field(default_factory=lambda: _new_id("context_access"))
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Default agent access policies


# Which context sources each agent type can access by default
DEFAULT_AGENT_POLICIES: dict[str, dict[str, tuple[str, ...]]] = {
    "coding": {
        "allow": ("project", "code", "task", "memory", "decision", "device", "runtime"),
        "deny": (),  # Currently none denied — Private User Context handled per-item
    },
    "planner": {
        "allow": ("project", "task", "memory", "decision"),
        "deny": ("device",),
    },
    "executor": {
        "allow": ("project", "task", "device", "runtime"),
        "deny": ("memory", "decision"),
    },
    "observer": {
        "allow": ("memory", "project", "runtime"),
        "deny": ("device", "agent"),
    },
}


# Context Guard


class ContextGuard:
    """Authorize and audit all context access through Governance.

    Usage::

        guard = ContextGuard(workspace="/path/to/.nous")
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_coding_01",
            actor_type="agent",
            purpose="continue project implementation",
            requested_sources=("project", "memory", "decision"),
            authorization_context=authenticated_context,
        ))
        if decision.allowed:
            # proceed
    """

    def __init__(self, workspace: str = "", *, gate: Any = None):
        self._workspace = str(Path(workspace or Path.cwd() / ".nous").resolve())
        root = Path(self._workspace)
        self._store = ContextStore(root if root.name == ".nous" else root / ".nous")
        self._gate = gate

    def authorize(self, request: ContextAccessRequest) -> ContextAccessDecision:
        """Admit the bound read using identity established by the trusted caller.

        Actor strings and metadata cannot establish authentication. Human reads
        additionally retain the existing local/session origin attestation.
        """
        sources_valid = isinstance(request.requested_sources, (tuple, list)) and all(
            isinstance(source, str) and source.strip()
            for source in request.requested_sources
        )
        requested = (
            tuple(sorted(set(request.requested_sources))) if sources_valid else ()
        )

        def deny(reason: str, decision_id: str = "") -> ContextAccessDecision:
            decision = ContextAccessDecision(reason=reason, denied_sources=requested)
            if decision_id:
                decision.decision_id = decision_id
            return self._finish(request, decision)

        context = request.authorization_context
        if (
            not isinstance(context, AuthorizationContext)
            or not isinstance(request.actor, str)
            or not isinstance(request.actor_type, str)
            or not request.actor.strip()
            or request.actor != context.subject_id
            or not isinstance(request.purpose, str)
            or not request.purpose.strip()
            or not isinstance(request.context_id, str)
            or not isinstance(request.metadata, dict)
            or not sources_valid
        ):
            return deny(
                "Context read requires a bound authenticated actor and stated purpose"
            )
        subject_types = {
            "agent": {"agent", "service", "automation"},
            "user": {"user"},
            "system": {"service", "automation"},
        }
        try:
            identity_valid = (
                context.subject_type in subject_types.get(request.actor_type, set())
                and isinstance(context.authn_method, str)
                and bool(context.authn_method.strip())
                and isinstance(context.context_id, str)
                and bool(context.context_id)
                and isinstance(context.authn_confidence, (int, float))
                and not isinstance(context.authn_confidence, bool)
                and math.isfinite(context.authn_confidence)
                and 0.5 <= context.authn_confidence <= 1.0
                and context.session_locality in {"local", "remote"}
            )
        except (TypeError, ValueError):
            identity_valid = False
        if not identity_valid:
            return deny("Context actor identity is unknown or inconsistent")

        if request.actor_type == "agent":
            allowed, policy_denied = self._agent_policy(request.actor)
        else:
            allowed = (
                "memory",
                "project",
                "agent",
                "device",
                "decision",
                "retrieval",
                "experience",
                "runtime",
            )
            policy_denied = ()
        requested = requested or tuple(sorted(allowed))
        granted = set(requested) & set(allowed) - set(policy_denied)
        denied = set(requested) - granted
        if not granted:
            return deny("No requested sources are permitted for the current actor")

        permission = request.metadata.get("permission", "read")
        classification = (
            {
                "read": "internal",
                "private": "confidential",
                "restricted": "restricted",
            }.get(permission)
            if isinstance(permission, str)
            else None
        )
        if classification is None:
            return deny("Context permission is unknown")
        if permission == "private" and (
            request.actor_type != "user"
            or not isinstance(request.metadata.get("owner_id"), str)
            or not request.metadata["owner_id"]
            or request.metadata["owner_id"] != context.subject_id
        ):
            return deny("Private context requires its authenticated owner")
        try:
            from nous_runtime.governance.gate import get_gate

            gate = self._gate or get_gate()
            if request.actor_type == "user" and not self._human_is_current(
                context, gate, request.context_id
            ):
                return deny("Current trusted human identity is required")
            proposal = ActionProposal(
                capability_id="context.read",
                action_type="context_access",
                agent_id=request.actor if request.actor_type == "agent" else "",
                target_workspace=self._workspace,
                locality=context.session_locality,
                affected_resources=(request.context_id or self._workspace,),
                params={
                    "context_id": request.context_id,
                    "actor_type": request.actor_type,
                    "sources": sorted(granted),
                    "purpose_sha256": hashlib.sha256(
                        request.purpose.encode("utf-8")
                    ).hexdigest(),
                    "permission": permission,
                    "owner_id": request.metadata.get("owner_id", ""),
                },
                parameter_summary="Read the bound context sources for the stated purpose",
                required_permissions=("context.read",),
                data_classification=classification,
                side_effect_class="read_only",
                reversibility="reversible",
                retry_behavior="idempotent",
            )
            admission = gate.evaluate(proposal, context)
            if (
                admission.action_mode != "EXECUTE"
                or admission.allowed is not True
                or not isinstance(admission.decision_id, str)
                or not admission.decision_id
            ):
                return deny(
                    "Governance did not admit context execution", admission.decision_id
                )
            persisted = gate.store.get_decision(admission.decision_id)
            if (
                not isinstance(persisted, dict)
                or persisted.get("allowed") is not True
                or any(
                    persisted.get(name) != expected
                    for name, expected in {
                        "decision_id": admission.decision_id,
                        "context_id": context.context_id,
                        "proposal_hash": proposal.proposal_hash,
                        "action_mode": "EXECUTE",
                    }.items()
                )
            ):
                return deny(
                    "Persisted governance decision does not bind this context read",
                    admission.decision_id,
                )
            decision = ContextAccessDecision(
                allowed=True,
                reason="Partial source access granted"
                if denied
                else "Context sources admitted",
                granted_sources=tuple(sorted(granted)),
                denied_sources=tuple(sorted(denied)),
                decision_id=admission.decision_id,
            )
            decision = self._finish(request, decision)
            if (
                decision.allowed
                and request.actor_type == "user"
                and not self._human_is_current(context, gate, request.context_id)
            ):
                return deny(
                    "Human identity changed before context delivery",
                    admission.decision_id,
                )
            return decision
        except Exception:
            _log.warning("Context governance is unavailable; read denied")
            return deny("Context governance is unavailable")

    def check_item_permission(
        self,
        item: ContextItem,
        actor: str = "",
        actor_type: str = "",
        *,
        authorization_context: AuthorizationContext | None = None,
        purpose: str = "",
    ) -> bool:
        """Check if an actor can read a specific context item.

        Private items are only visible to the owning user. Restricted items
        require explicit authorization.
        """
        owner = (
            item.metadata.get("owner_id") if isinstance(item.metadata, dict) else None
        )
        request = ContextAccessRequest(
            actor=actor,
            actor_type=actor_type,
            context_id=item.item_id,
            purpose=purpose,
            requested_sources=(item.source_type,),
            metadata={"permission": item.permission, "owner_id": owner or ""},
            authorization_context=authorization_context,
        )
        if item.validate() or not isinstance(item.metadata, dict):
            self._finish(
                request,
                ContextAccessDecision(
                    reason="Context item is invalid",
                    denied_sources=(item.source_type,),
                ),
            )
            return False
        if item.permission == "private" and (
            actor_type != "user"
            or not isinstance(owner, str)
            or not owner
            or not isinstance(authorization_context, AuthorizationContext)
            or owner != authorization_context.subject_id
        ):
            self._finish(
                request,
                ContextAccessDecision(
                    reason="Private context requires its authenticated owner",
                    denied_sources=(item.source_type,),
                ),
            )
            return False
        decision = self.authorize(request)
        return decision.allowed

    def filter_items(
        self,
        items: list[ContextItem],
        actor: str = "",
        actor_type: str = "",
        *,
        authorization_context: AuthorizationContext | None = None,
        purpose: str = "",
    ) -> list[ContextItem]:
        """Filter context items to only those the actor can access."""
        return [
            item
            for item in items
            if self.check_item_permission(
                item,
                actor,
                actor_type,
                authorization_context=authorization_context,
                purpose=purpose,
            )
        ]

    # Audit

    def _finish(
        self, request: ContextAccessRequest, decision: ContextAccessDecision
    ) -> ContextAccessDecision:
        if not self._audit(request, decision):
            return ContextAccessDecision(
                reason="Context audit is unavailable",
                denied_sources=tuple(
                    sorted(set(decision.granted_sources + decision.denied_sources))
                ),
                decision_id=decision.decision_id,
            )
        return decision

    def _audit(
        self, request: ContextAccessRequest, decision: ContextAccessDecision
    ) -> bool:
        """Record an audit entry for this context access."""
        try:
            context = request.authorization_context
            record = redact_sensitive_data(
                {
                    "snapshot_id": request.context_id or "context_access",
                    "actor": request.actor,
                    "purpose": request.purpose,
                    "decision": "allow" if decision.allowed else "deny",
                    "metadata": {
                        "actor_type": request.actor_type,
                        "requested_sources": list(request.requested_sources),
                        "granted_sources": list(decision.granted_sources),
                        "denied_sources": list(decision.denied_sources),
                        "reason": decision.reason,
                        "decision_id": decision.decision_id,
                        "authorization_context_id": context.context_id
                        if isinstance(context, AuthorizationContext)
                        else "",
                        "workspace": self._workspace,
                    },
                }
            )
            return (
                self._store.record_audit(
                    **record,
                )
                is True
            )
        except Exception:
            _log.error("Context audit failed; read denied")
            return False

    def get_audit_log(
        self,
        actor: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve the context access audit log."""
        return self._store.get_audit_log(actor=actor, limit=limit)

    # Helpers

    def _agent_policy(self, agent_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Determine allow/deny sources for an agent."""
        try:
            from nous_runtime.agent.registry import AgentRegistry

            profile = AgentRegistry(self._workspace).get(agent_id)
            if profile is None:
                return (), ()
            metadata = profile.manifest.metadata
            agent_type = metadata.get("role", metadata.get("kind", "coding"))
            if not isinstance(agent_type, str):
                return (), ()
            agent_type = agent_type.lower()
            policy = DEFAULT_AGENT_POLICIES.get(agent_type)
            if policy is None:
                return (), ()
            return policy["allow"], policy["deny"]
        except Exception:
            _log.warning("Context agent policy is unavailable; read denied")
            return (), ()

    @staticmethod
    def _human_is_current(
        context: AuthorizationContext, gate: Any, resource: str
    ) -> bool:
        from nous_runtime.control_plane.human_sessions import (
            human_permission,
            is_human_session_context,
        )
        from nous_runtime.governance.cli import _is_local_owner_context

        return bool(
            context.subject_type == "user"
            and context.authn_confidence >= 0.8
            and (
                (
                    _is_local_owner_context(context)
                    and context.authn_method == "cli_os_user"
                    and context.session_locality == "local"
                )
                or (
                    is_human_session_context(context, gate.store)
                    and human_permission(context, "context.read", resource)
                )
            )
        )


# Convenience


def authorize_context_access(
    actor: str,
    actor_type: str,
    purpose: str,
    sources: tuple[str, ...] = (),
    workspace: str = "",
    *,
    authorization_context: AuthorizationContext | None = None,
) -> ContextAccessDecision:
    """One-shot context access authorization."""
    guard = ContextGuard(workspace)
    return guard.authorize(
        ContextAccessRequest(
            actor=actor,
            actor_type=actor_type,
            purpose=purpose,
            requested_sources=sources,
            authorization_context=authorization_context,
        )
    )
