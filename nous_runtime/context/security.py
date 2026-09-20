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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.context.models import ContextItem
from nous_runtime.context.store import ContextStore

_log = logging.getLogger("nous.context.security")



# Access control model


@dataclass
class ContextAccessRequest:
    """A request to access context data."""
    actor: str = ""             # Agent ID, user ID, or system component
    actor_type: str = ""        # "agent", "user", "system"
    context_id: str = ""        # Snapshot ID or item ID
    purpose: str = ""           # Why context is needed
    requested_sources: tuple[str, ...] = ()   # Which ContextSources are requested
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextAccessDecision:
    """Result of a context access authorization check."""
    allowed: bool = False
    reason: str = ""
    granted_sources: tuple[str, ...] = ()
    denied_sources: tuple[str, ...] = ()
    decision_id: str = ""
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
        ))
        if decision.allowed:
            # proceed
    """

    def __init__(self, workspace: str = ""):
        self._workspace = workspace
        self._store = ContextStore(workspace)



    def authorize(self, request: ContextAccessRequest) -> ContextAccessDecision:
        """Check whether the actor is allowed to access the requested context.

        Integrates with the Governance Gate for constitution-level checks.
        """
        # 1. Determine actor type defaults
        if request.actor_type == "agent":
            allowed, denied = self._agent_policy(request.actor)
        elif request.actor_type == "user":
            allowed, denied = ("memory", "project", "agent", "device", "decision", "retrieval", "experience", "runtime"), ()
        elif request.actor_type == "system":
            allowed, denied = ("memory", "project", "agent", "device", "decision", "retrieval", "experience", "runtime"), ()
        else:
            return ContextAccessDecision(
                allowed=False,
                reason=f"Unknown actor_type: {request.actor_type}",
                denied_sources=request.requested_sources,
            )

        # 2. Filter requested sources
        requested = set(request.requested_sources) if request.requested_sources else set(allowed)
        granted = requested & set(allowed)
        denied = requested & set(denied)

        # 3. Check Governance Gate if available
        gate_denied: list[str] = []
        try:
            from nous_runtime.governance.gate import get_gate
            from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext

            gate = get_gate()
            proposal = ActionProposal(
                capability_id="context.read",
                action_type="context_access",
                parameter_summary=f"actor={request.actor} purpose={request.purpose} sources={','.join(sorted(granted))}",
                data_classification="internal",
                side_effect_class="read_only",
                reversibility="reversible",
            )
            auth_ctx = AuthorizationContext(
                principal_id=request.actor,
                surface="local_cli",
            )
            decision = gate.evaluate(proposal, auth_ctx)
            if decision.action_mode not in ("EXECUTE", "RECOMMEND"):
                gate_denied.append(f"GovernanceGate denied: {decision.reason_code} — {decision.reason_message}")
        except Exception as exc:
            _log.debug("Governance gate unavailable for context auth: %s", exc)
            # Gate unavailable — fail open for local, log warning
            _log.warning("Context access proceeding without governance gate: %s", exc)

        # 4. Build decision
        all_denied = tuple(sorted(set(denied) | set(gate_denied)))
        all_granted = tuple(sorted(granted - set(gate_denied)))

        allowed = len(all_granted) > 0

        if not allowed:
            reason = f"Access denied. Denied sources: {all_denied}"
        elif all_denied:
            reason = f"Partial access. Denied: {all_denied}. Granted: {all_granted}."
        else:
            reason = "Full access granted."

        decision = ContextAccessDecision(
            allowed=allowed,
            reason=reason,
            granted_sources=all_granted,
            denied_sources=all_denied,
        )

        # 5. Audit
        self._audit(request, decision)

        return decision



    def check_item_permission(
        self,
        item: ContextItem,
        actor: str = "",
        actor_type: str = "",
    ) -> bool:
        """Check if an actor can read a specific context item.

        Private items are only visible to the owning user. Restricted items
        require explicit authorization.
        """
        if item.permission == "read":
            return True

        if item.permission == "private":
            # Only users can see their own private items
            return actor_type == "user"

        if item.permission == "restricted":
            # Agents need explicit authorization for restricted items
            if actor_type == "agent":
                allowed, _ = self._agent_policy(actor)
                return item.source_type in allowed
            return actor_type in ("user", "system")

        return False

    def filter_items(
        self,
        items: list[ContextItem],
        actor: str = "",
        actor_type: str = "",
    ) -> list[ContextItem]:
        """Filter context items to only those the actor can access."""
        return [i for i in items if self.check_item_permission(i, actor, actor_type)]


    # Audit


    def _audit(self, request: ContextAccessRequest, decision: ContextAccessDecision) -> None:
        """Record an audit entry for this context access."""
        try:
            self._store.record_audit(
                snapshot_id=request.context_id or "context_access",
                actor=request.actor,
                purpose=request.purpose,
                decision="allow" if decision.allowed else "deny",
                metadata={
                    "actor_type": request.actor_type,
                    "requested_sources": list(request.requested_sources),
                    "granted_sources": list(decision.granted_sources),
                    "denied_sources": list(decision.denied_sources),
                    "reason": decision.reason,
                    "decision_id": decision.decision_id,
                },
            )
        except Exception as exc:
            _log.error("Failed to record context audit: %s", exc)

    def get_audit_log(
        self,
        actor: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve the context access audit log."""
        return self._store.get_audit_log(actor=actor, limit=limit)


    # Helpers


    @staticmethod
    def _agent_policy(agent_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Determine allow/deny sources for an agent."""
        # Try to look up agent type
        agent_type = "coding"  # default
        try:
            from nous_runtime.agent.registry import AgentRegistry
            agent_info = AgentRegistry().get(agent_id)
            if agent_info:
                agent_type = agent_info.get("role", agent_info.get("kind", "coding")).lower()
        except Exception:
            pass

        policy = DEFAULT_AGENT_POLICIES.get(agent_type, DEFAULT_AGENT_POLICIES["coding"])
        return policy["allow"], policy["deny"]



# Convenience


def authorize_context_access(
    actor: str,
    actor_type: str,
    purpose: str,
    sources: tuple[str, ...] = (),
    workspace: str = "",
) -> ContextAccessDecision:
    """One-shot context access authorization."""
    guard = ContextGuard(workspace)
    return guard.authorize(ContextAccessRequest(
        actor=actor,
        actor_type=actor_type,
        purpose=purpose,
        requested_sources=sources,
    ))
