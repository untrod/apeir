# -*- coding: utf-8 -*-
"""CommandPolicyEvaluator — evaluates whether a proposed command should be allowed."""

from __future__ import annotations

from nous_runtime.agents.external.models import AgentCommandProposal, AgentDescriptor


class CommandPolicyEvaluator:
    """Evaluates agent command proposals against policy.

    Default policy tiers:
    - Low risk: read-only operations (allowed)
    - Conditional: file modifications, tests (approval required)
    - Always require approval: package install, network ops, destructive ops
    """

    # Commands that are always allowed (read-only inspection)
    _READ_ONLY_PREFIXES: tuple[tuple[str, ...], ...] = (
        ("ls",),
        ("dir",),
        ("cat",),
        ("type",),
        ("head",),
        ("tail",),
        ("wc",),
        ("find",),
        ("grep",),
        ("rg",),
        ("git", "status"),
        ("git", "log"),
        ("git", "diff"),
        ("git", "show"),
        ("echo",),
        ("pwd",),
        ("cd",),
        ("which",),
        ("where",),
        ("whoami",),
        ("hostname",),
        ("date",),
        ("env",),
        ("printenv",),
    )

    # Commands that always require approval
    _ALWAYS_APPROVE_PREFIXES: tuple[tuple[str, ...], ...] = (
        ("pip", "install"),
        ("npm", "install"),
        ("npm", "i"),
        ("yarn", "add"),
        ("apt", "install"),
        ("apt-get", "install"),
        ("brew", "install"),
        ("choco", "install"),
        ("git", "push"),
        ("git", "commit"),
        ("rm",),
        ("rmdir",),
        ("del",),
        ("rd",),
        ("format",),
        ("mkfs",),
        ("dd",),
        ("shutdown",),
        ("reboot",),
        ("sudo",),
        ("su",),
        ("chmod", "777"),
        ("chown",),
        ("scp",),
        ("ssh",),
        ("curl",),
        ("wget",),
        ("nc",),
        ("netcat",),
        ("telnet",),
    )

    # Commands that need approval if they modify files
    _WRITE_PREFIXES: tuple[tuple[str, ...], ...] = (
        ("git", "add"),
        ("git", "checkout"),
        ("git", "branch", "-D"),
        ("git", "branch", "-d"),
        ("mv",),
        ("move",),
        ("copy",),
        ("cp",),
        ("mkdir",),
        ("touch",),
        ("sed",),
        ("awk",),
        ("tee",),
    )

    def __init__(self, *, descriptor: AgentDescriptor | None = None):
        self._descriptor = descriptor

    def evaluate(self, proposal: AgentCommandProposal) -> str:
        """Evaluate a command proposal.

        Returns:
            "allow" — execute without approval
            "ask" — require approval
            "deny" — reject immediately
        """
        if not proposal.command:
            return "deny"

        cmd = tuple(str(a).lower() for a in proposal.command)

        # Deny empty commands
        if not cmd or not cmd[0]:
            return "deny"

        # Always approve: read-only commands
        for prefix in self._READ_ONLY_PREFIXES:
            if self._matches_prefix(cmd, prefix):
                return "allow"

        # Always deny: destructive / network / install commands
        for prefix in self._ALWAYS_APPROVE_PREFIXES:
            if self._matches_prefix(cmd, prefix):
                return "ask"

        # Write commands need approval
        for prefix in self._WRITE_PREFIXES:
            if self._matches_prefix(cmd, prefix):
                return "ask"

        # Unknown commands default to requiring approval
        return "ask"

    @staticmethod
    def _matches_prefix(cmd: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
        """Check if cmd starts with the given prefix."""
        if len(cmd) < len(prefix):
            return False
        for i, part in enumerate(prefix):
            if cmd[i] != part:
                return False
        return True

    @staticmethod
    def classify_risk(cmd: tuple[str, ...]) -> str:
        """Classify command risk level: low, medium, high, critical."""
        cmd_lower = tuple(str(a).lower() for a in cmd)
        evaluator = CommandPolicyEvaluator()
        for prefix in evaluator._ALWAYS_APPROVE_PREFIXES:
            if evaluator._matches_prefix(cmd_lower, prefix):
                return "high"
        for prefix in evaluator._WRITE_PREFIXES:
            if evaluator._matches_prefix(cmd_lower, prefix):
                return "medium"
        for prefix in evaluator._READ_ONLY_PREFIXES:
            if evaluator._matches_prefix(cmd_lower, prefix):
                return "low"
        return "medium"

    @staticmethod
    def is_destructive(cmd: tuple[str, ...]) -> bool:
        """Check if a command is potentially destructive."""
        destructive = {
            "rm", "rmdir", "del", "rd", "format", "mkfs", "dd",
            "shutdown", "reboot", "sudo",
        }
        if not cmd:
            return False
        return cmd[0].lower() in destructive
