"""Native Windows owner-policy admission is handle and ACL bound."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from nous_runtime.governance.permission import (
    PermissionEngine,
    PermissionRequest,
)
from nous_runtime.security.private_files import restrict_owner_only_file


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Native Windows owner-policy contract"
)


def _policy(root: Path, *, allow: bool = True) -> Path:
    target = root / ".nous" / "permission-policy.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "subject": "api-service",
                        "action": "context.read",
                        "resource": "*",
                        "effect": "allow" if allow else "deny",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    restrict_owner_only_file(target, subject="test owner policy")
    return target


def test_current_user_only_policy_loads_and_reloads_revocation(tmp_path):
    path = _policy(tmp_path)
    engine = PermissionEngine.from_owner_file(path)
    request = PermissionRequest("api-service", "context.read", "snapshot-1")
    assert engine.check(request).allowed is True
    before = engine.configuration_status()["policy_sha256"]

    _policy(tmp_path, allow=False)
    assert engine.check(request).allowed is False
    assert engine.configuration_status()["policy_sha256"] != before


def test_inherited_or_broadened_policy_acl_fails_closed(tmp_path):
    path = _policy(tmp_path)
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:e"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(PermissionError):
        PermissionEngine.from_owner_file(path)


def test_additional_system_ace_fails_closed(tmp_path):
    path = _policy(tmp_path)
    result = subprocess.run(
        ["icacls", str(path), "/grant", "*S-1-5-18:(F)"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(PermissionError):
        PermissionEngine.from_owner_file(path)


def test_hard_link_policy_fails_closed(tmp_path):
    path = _policy(tmp_path)
    os.link(path, path.with_name("policy-alias.json"))
    with pytest.raises(PermissionError):
        PermissionEngine.from_owner_file(path)


@pytest.mark.parametrize(
    "name",
    [
        "permission-policy.json:stream",
        "PERMIS~1.JSO",
        "permission-policy.json.",
        "permission-policy.json ",
    ],
)
def test_ambiguous_policy_name_fails_before_content_admission(tmp_path, name):
    ordinary = _policy(tmp_path)
    ambiguous = ordinary.with_name(name)
    with pytest.raises((OSError, PermissionError)):
        PermissionEngine.from_owner_file(ambiguous)
