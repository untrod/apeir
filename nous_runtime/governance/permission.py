"""Compact Subject/Action/Resource/Context permission policy."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
                key in request.context
                and type(request.context[key]) is type(value)
                and request.context[key] == value
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
        self._policy_path: Path | None = None

    @classmethod
    def from_owner_file(cls, path: Path) -> "PermissionEngine":
        """Read explicit host policy; this does not issue a grant or permission."""
        engine = cls()
        engine._policy_path = Path(path)
        engine._owner_rules()  # Reject invalid startup policy before admission.
        return engine

    def _owner_rules(self) -> tuple[tuple[PermissionRule, ...], str]:
        path = self._policy_path
        if path is None:
            return tuple(self._rules), ""
        if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
            raise PermissionError(
                "Owner policy file access is not qualified on this host"
            )
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or parent.st_mode & 0o022
        ):
            raise PermissionError("Owner policy requires a protected state directory")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.getuid()
                or before.st_mode & 0o077
                or not 0 < before.st_size <= 65536
            ):
                raise PermissionError(
                    "Owner policy requires a bounded owner-only single-link file"
                )
            data = bytearray()
            while chunk := os.read(descriptor, min(8192, 65537 - len(data))):
                data.extend(chunk)
                if len(data) > 65536:
                    raise PermissionError("Owner policy exceeds its byte bound")
            after = os.fstat(descriptor)
            if (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ) or len(data) != before.st_size:
                raise PermissionError("Owner policy changed during inspection")
        finally:
            os.close(descriptor)
        try:

            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError
                    value[key] = item
                return value

            value = json.loads(bytes(data), object_pairs_hook=unique_object)
            if (
                not isinstance(value, dict)
                or set(value) - {"rules", "expires_at"}
                or not isinstance(value.get("rules"), list)
                or len(value["rules"]) > 128
            ):
                raise ValueError
            expires = value.get("expires_at", "")
            if not isinstance(expires, str):
                raise ValueError
            if expires:
                deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
                    raise ValueError
            elif expires != "":
                raise ValueError
            from nous_runtime.core.redaction import redact_sensitive_data

            if redact_sensitive_data(value) != value:
                raise ValueError
            rules = []
            for item in value["rules"]:
                if (
                    not isinstance(item, dict)
                    or set(item)
                    - {"subject", "action", "resource", "effect", "context_equals"}
                    or any(
                        not isinstance(item.get(key), str)
                        or not 0 < len(item[key]) <= 1024
                        or any(ord(c) < 32 for c in item[key])
                        for key in ("subject", "action", "resource")
                    )
                    or item.get("effect", "allow") not in {"allow", "deny"}
                    or not isinstance(item.get("context_equals", {}), dict)
                    or len(item.get("context_equals", {})) > 32
                    or any(
                        not isinstance(key, str)
                        or not 0 < len(key) <= 128
                        or type(condition) not in {str, bool, int}
                        for key, condition in item.get("context_equals", {}).items()
                    )
                ):
                    raise ValueError
                rules.append(PermissionRule(**item))
            return tuple(rules), hashlib.sha256(data).hexdigest()
        except (TypeError, ValueError, UnicodeError):
            raise PermissionError(
                "Owner permission policy is invalid or expired"
            ) from None

    def configuration_status(self) -> dict[str, Any]:
        rules, digest = self._owner_rules()
        return {
            "source": "owner-file" if self._policy_path is not None else "trusted-host",
            "rule_count": len(rules),
            "policy_sha256": digest or None,
        }

    def add(self, rule: PermissionRule) -> PermissionRule:
        if self._policy_path is not None:
            raise PermissionError(
                "File-backed rules are changed only by their trusted owner"
            )
        self._rules.append(rule)
        return rule

    def check(self, request: PermissionRequest) -> PermissionDecision:
        try:
            rules, _digest = self._owner_rules()
        except (OSError, PermissionError):
            return PermissionDecision(False, "permission policy unavailable")
        matches = [rule for rule in rules if rule.matches(request)]
        denied = next(
            (rule for rule in matches if rule.effect.strip().lower() == "deny"),
            None,
        )
        if denied is not None:
            return PermissionDecision(False, "explicit deny", denied)
        allowed = next(
            (rule for rule in matches if rule.effect.strip().lower() == "allow"),
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
