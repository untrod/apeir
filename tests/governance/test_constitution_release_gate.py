from datetime import datetime, timedelta, timezone

import pytest

from nous_runtime.governance.constitution import evaluate_constitution
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext


def ctx(**overrides):
    values = {
        "subject_type": "user",
        "subject_id": "subject-a",
        "authn_method": "cli_os_user",
        "authn_confidence": 0.95,
        "session_locality": "local",
    }
    values.update(overrides)
    return AuthorizationContext(**values)


def prop(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "system.echo",
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "created_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return ActionProposal(**values)


def expired_time():
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(
    ("rule_id", "proposal", "context"),
    [
        ("N1", prop(), ctx(subject_type="model")),
        ("N2", prop(action_type="audit.delete"), ctx()),
        ("N3", prop(action_type="approval.scope.expand"), ctx()),
        ("N4", prop(expires_at=expired_time()), ctx()),
        ("N5", prop(action_type="authorization.reuse_revoked"), ctx()),
        ("N6", prop(required_permissions=("sandbox.bypass",)), ctx()),
        ("N7", prop(affected_resources=("../outside.txt",)), ctx()),
        ("N8", prop(capability_id="node.manifest.bypass"), ctx()),
        ("N9", prop(capability_id="device.pc.exec"), ctx(authn_confidence=0.6)),
        ("N10", prop(action_type="deployment.promote", deployment_channel="production", proposal_hash=""), ctx()),
        ("N11", prop(action_type="policy.modify"), ctx(subject_type="model")),
        ("N13", prop(action_type="gate.bypass"), ctx()),
    ],
)
def test_non_overridable_constitution_rules(rule_id, proposal, context):
    violations = evaluate_constitution(proposal, context)
    assert any(v.rule_id == rule_id for v in violations)


def test_n12_fault_injection_denied_in_production(monkeypatch):
    monkeypatch.setenv("NOUS_ENV", "production")
    violations = evaluate_constitution(prop(capability_id="reliability.fault_injection"), ctx())
    assert any(v.rule_id == "N12" for v in violations)


@pytest.mark.parametrize(
    "capability_id",
    ["device.pc.exec", "device.pc.shell", "tool.sudo", "credential.bypass"],
)
def test_privileged_capabilities_require_high_confidence(capability_id):
    violations = evaluate_constitution(prop(capability_id=capability_id), ctx(authn_confidence=0.4))
    assert any(v.rule_id == "N9" for v in violations)
