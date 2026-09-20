"""Compact Subject/Action/Resource/Context permission policy."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PermissionRequest:
    subject: str
    action: str
    resource: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PermissionRule:
    subject: str
    action: str
    resource: str
    effect: str = "allow"
    context_equals: Mapping[str, Any] = field(default_factory=dict)

    def matches(self, request: PermissionRequest) -> bool:
        return (
            fnmatch.fnmatchcase(request.subject, self.subject)
            and fnmatch.fnmatchcase(request.action, self.action)
            and fnmatch.fnmatchcase(request.resource, self.resource)
            and all(
                request.context.get(key) == value
                for key, value in self.context_equals.items()
            )
        )


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str
    matched_rule: PermissionRule | None = None


class PermissionEngine:
    """Deny-by-default permission engine with explicit deny precedence."""

    def __init__(self, rules: tuple[PermissionRule, ...] = ()) -> None:
        self._rules = list(rules)

    def add(self, rule: PermissionRule) -> PermissionRule:
        self._rules.append(rule)
        return rule

    def check(self, request: PermissionRequest) -> PermissionDecision:
        matches = [rule for rule in self._rules if rule.matches(request)]
        denied = next(
            (
                rule
                for rule in matches
                if rule.effect.strip().lower() == "deny"
            ),
            None,
        )
        if denied is not None:
            return PermissionDecision(False, "explicit deny", denied)
        allowed = next(
            (
                rule
                for rule in matches
                if rule.effect.strip().lower() == "allow"
            ),
            None,
        )
        if allowed is not None:
            return PermissionDecision(True, "explicit allow", allowed)
        return PermissionDecision(False, "no matching permission rule")


__all__ = [
    "PermissionDecision",
    "PermissionEngine",
    "PermissionRequest",
    "PermissionRule",
]
