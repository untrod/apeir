"""Explicit host policy input extends the existing Gate, never discovery trust."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.governance.permission import (
    PermissionEngine,
    PermissionRequest,
    PermissionRule,
)


pytestmark = pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "O_NOFOLLOW"),
    reason="Owner file policy requires qualified POSIX no-follow access",
)


def policy(root: Path, value=None):
    target = root / ".nous" / "permission-policy.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    target.write_text(
        json.dumps(
            value
            if value is not None
            else {
                "rules": [
                    {
                        "subject": "api-service",
                        "action": "context.read",
                        "resource": "*",
                    },
                ]
            }
        )
    )
    target.chmod(0o600)
    return target


def test_discovered_policy_cannot_configure_authority(tmp_path, monkeypatch):
    policy(tmp_path)
    monkeypatch.delenv("NOUS_PERMISSION_POLICY", raising=False)
    assert (
        ExecutionAuthorizationGate(
            GovernanceStore(tmp_path / ".nous")
        ).permission_engine
        is None
    )


def test_explicit_owner_policy_reloads_revocation_and_restart(tmp_path, monkeypatch):
    path = policy(tmp_path)
    monkeypatch.setenv("NOUS_PERMISSION_POLICY", str(path))
    gate = ExecutionAuthorizationGate(GovernanceStore(tmp_path / ".nous"))
    request = PermissionRequest("api-service", "context.read", "snapshot-1")
    assert gate.permission_engine.check(request).allowed is True
    first = gate.permission_engine.configuration_status()
    assert first["rule_count"] == 1
    assert first["policy_sha256"]
    policy(
        tmp_path,
        {
            "rules": [
                {
                    "subject": "api-service",
                    "action": "context.read",
                    "resource": "*",
                    "effect": "deny",
                }
            ]
        },
    )
    assert gate.permission_engine.check(request).allowed is False
    assert (
        gate.permission_engine.configuration_status()["policy_sha256"]
        != first["policy_sha256"]
    )
    assert (
        ExecutionAuthorizationGate(GovernanceStore(tmp_path / ".nous"))
        .permission_engine.check(request)
        .allowed
        is False
    )
    with pytest.raises(PermissionError):
        gate.permission_engine.add(PermissionRule("*", "*", "*"))
    path.unlink()
    assert gate.permission_engine.check(request).allowed is False


@pytest.mark.parametrize(
    "change", ["symlink", "hardlink", "mode", "directory_mode", "nonregular"]
)
def test_untrusted_file_shape_cannot_configure_policy(tmp_path, change):
    path = policy(tmp_path)
    if change == "symlink":
        saved = path.with_name("saved.json")
        path.rename(saved)
        path.symlink_to(saved)
    elif change == "hardlink":
        os.link(path, path.with_name("alias.json"))
    elif change == "mode":
        path.chmod(0o644)
    elif change == "directory_mode":
        path.parent.chmod(0o777)
    else:
        path.unlink()
        os.mkfifo(path)
    with pytest.raises((PermissionError, OSError)):
        PermissionEngine.from_owner_file(path)


@pytest.mark.parametrize(
    "value",
    [
        {"rules": [], "expires_at": True},
        {"rules": [], "expires_at": "2020-01-01T00:00:00Z"},
        {"rules": [], "expires_at": "invalid"},
        {"rules": [], "authority": "model"},
        {
            "rules": [
                {"subject": "a", "action": "*", "resource": "*", "effect": "unknown"}
            ]
        },
        {
            "rules": [
                {
                    "subject": "a",
                    "action": "*",
                    "resource": "*",
                    "context_equals": {"api_key": "FAKE_ONLY_POLICY_VALUE"},
                }
            ]
        },
    ],
)
def test_invalid_expired_or_sensitive_policy_denies(tmp_path, value):
    path = policy(tmp_path, value)
    with pytest.raises(PermissionError):
        PermissionEngine.from_owner_file(path)


def test_expiry_and_corruption_never_reuse_cached_allow(tmp_path):
    path = policy(
        tmp_path,
        {
            "rules": [{"subject": "a", "action": "*", "resource": "*"}],
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=1)
            ).isoformat(),
        },
    )
    engine = PermissionEngine.from_owner_file(path)
    request = PermissionRequest("a", "workspace.read", "workspace:one")
    assert engine.check(request).allowed
    path.write_text('{"rules":[],"rules":[]}')
    assert not engine.check(request).allowed
    with pytest.raises(PermissionError):
        engine.configuration_status()


def test_policy_cannot_be_selected_from_other_workspace(tmp_path, monkeypatch):
    other = tmp_path / "other"
    path = policy(other)
    monkeypatch.setenv("NOUS_PERMISSION_POLICY", str(path))
    with pytest.raises(PermissionError):
        ExecutionAuthorizationGate(GovernanceStore(tmp_path / "selected" / ".nous"))


@pytest.mark.parametrize(
    ("expected", "actual"), [(True, 1), (1, True), (None, "absent")]
)
def test_context_conditions_require_present_exact_typed_facts(expected, actual):
    engine = PermissionEngine(
        (PermissionRule("a", "read", "*", context_equals={"fact": expected}),)
    )
    context = {} if actual == "absent" else {"fact": actual}
    assert not engine.check(PermissionRequest("a", "read", "r", context)).allowed
    assert engine.check(PermissionRequest("a", "read", "r", {"fact": expected})).allowed
