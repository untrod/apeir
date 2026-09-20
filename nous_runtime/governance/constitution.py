# -*- coding: utf-8 -*-
"""Runtime Constitution -13 non-overridable safety rules."""

from __future__ import annotations

from dataclasses import dataclass
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext


@dataclass(frozen=True)
class ConstitutionViolation:
    rule_id: str    # e.g., "N1", "N2"
    message: str
    detail: str = ""


def evaluate_constitution(
    proposal: ActionProposal,
    context: AuthorizationContext,
) -> list[ConstitutionViolation]:
    """Evaluate all 13 non-overridable rules. Returns list of violations.

    If the list is empty, the proposal passes Constitution review.
    Any violation 鈫?DENY (non-overridable).
    """
    violations: list[ConstitutionViolation] = []

    # N1: No model self-approval
    if context.subject_type == "model":
        violations.append(ConstitutionViolation(
            "N1", "Model self-approval is prohibited",
            f"subject_type={context.subject_type}"
        ))

    # N2: No audit deletion or silent alteration
    if proposal.action_type in ("audit.delete", "audit.modify", "audit.purge"):
        violations.append(ConstitutionViolation(
            "N2", "Audit deletion or alteration is prohibited",
            f"action_type={proposal.action_type}"
        ))

    # N3: No implicit approval-scope expansion
    if proposal.action_type in ("approval.scope.expand", "authorization.scope.expand") or "scope.expand" in proposal.required_permissions:
        violations.append(ConstitutionViolation(
            "N3", "Implicit approval-scope expansion is prohibited",
            f"action_type={proposal.action_type}, required_permissions={proposal.required_permissions}"
        ))

    # N4: No expired authorization reuse
    if proposal.expires_at:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if proposal.expires_at < now:
            violations.append(ConstitutionViolation(
                "N4", "Expired proposal cannot authorize execution",
                f"expires_at={proposal.expires_at}, now={now}"
            ))

    # N5: No revoked authorization reuse
    if proposal.action_type == "authorization.reuse_revoked" or "authorization.revoked" in proposal.required_permissions:
        violations.append(ConstitutionViolation(
            "N5", "Revoked authorization reuse is prohibited",
            f"action_type={proposal.action_type}, required_permissions={proposal.required_permissions}"
        ))

    # N6: No sandbox bypass
    if "sandbox.bypass" in proposal.required_permissions or "sandbox.disable" in proposal.required_permissions:
        violations.append(ConstitutionViolation(
            "N6", "Sandbox bypass is prohibited",
            f"required_permissions={proposal.required_permissions}"
        ))

    # N7: No workspace-boundary bypass
    if proposal.affected_resources:
        import os
        for resource in proposal.affected_resources:
            resolved = os.path.realpath(resource) if os.path.exists(resource) else resource
            if ".." in resource or resolved.startswith(("/etc/", "/var/run/", "/sys/", "/proc/")):
                violations.append(ConstitutionViolation(
                    "N7", "Workspace boundary bypass detected",
                    f"resource={resource}, resolved={resolved}"
                ))
                break

    # N8: No node-manifest bypass
    if proposal.capability_id == "node.manifest.bypass" or "node.manifest.bypass" in proposal.required_permissions:
        violations.append(ConstitutionViolation(
            "N8", "Node manifest bypass is prohibited",
            f"capability={proposal.capability_id}, required_permissions={proposal.required_permissions}"
        ))

    # N9: No unrestricted privilege escalation
    # (checked via risk engine; flagged here)
    if proposal.capability_id in ("device.pc.shell", "device.pc.exec", "tool.sudo", "credential.bypass"):
        if context.authn_confidence < 0.9:
            violations.append(ConstitutionViolation(
                "N9", "Privileged execution requires high-confidence authentication",
                f"capability={proposal.capability_id}, confidence={context.authn_confidence}"
            ))

    # N10: No automatic stable promotion
    if proposal.action_type == "deployment.promote" and getattr(proposal, "deployment_channel", "") in ("production", "stable"):
        violations.append(ConstitutionViolation(
            "N10", "Automatic stable promotion is prohibited",
            f"deployment_channel={getattr(proposal, 'deployment_channel', '')}"
        ))

    # N11: No model-controlled governance thresholds
    if context.subject_type == "model" and proposal.action_type in (
        "policy.modify", "policy.create", "policy.delete",
        "constitution.modify", "threshold.modify",
    ):
        violations.append(ConstitutionViolation(
            "N11", "Model-controlled governance modification is prohibited",
            f"subject_type={context.subject_type}, action_type={proposal.action_type}"
        ))

    # N12: No untrusted activation of fault injection
    if proposal.capability_id in ("reliability.fault_injection", "test.fault_injection"):
        import os
        env = os.environ.get("NOUS_ENV", "")
        if env == "production":
            violations.append(ConstitutionViolation(
                "N12", "Fault injection activation in production is prohibited",
                f"NOUS_ENV={env}"
            ))

    # N13: No hidden execution path around the canonical gate
    # (architectural -enforced by code review and static analysis)
    if proposal.action_type == "gate.bypass" or proposal.capability_id == "gate.bypass":
        violations.append(ConstitutionViolation(
            "N13", "Gate bypass is prohibited",
            f"action_type={proposal.action_type}"
        ))

    return violations
