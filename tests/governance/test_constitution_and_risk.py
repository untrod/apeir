from datetime import datetime, timedelta, timezone

from nous_runtime.governance.constitution import evaluate_constitution
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance.risk_engine import assess_risk


def context(**overrides):
    values = {
        "subject_type": "user",
        "subject_id": "user-a",
        "authn_method": "cli_os_user",
        "authn_confidence": 0.9,
        "session_locality": "local",
    }
    values.update(overrides)
    return AuthorizationContext(**values)


def proposal(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "system.echo",
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "data_classification": "internal",
    }
    values.update(overrides)
    return ActionProposal(**values)


def test_constitution_rejects_model_self_approval():
    violations = evaluate_constitution(proposal(), context(subject_type="model"))
    assert any(v.rule_id == "N1" for v in violations)


def test_constitution_rejects_audit_deletion():
    violations = evaluate_constitution(proposal(action_type="audit.delete"), context())
    assert any(v.rule_id == "N2" for v in violations)


def test_constitution_rejects_expired_proposal():
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    violations = evaluate_constitution(proposal(expires_at=expired), context())
    assert any(v.rule_id == "N4" for v in violations)


def test_constitution_rejects_sandbox_bypass_and_gate_bypass():
    violations = evaluate_constitution(
        proposal(capability_id="gate.bypass", required_permissions=("sandbox.bypass",)),
        context(),
    )
    assert {v.rule_id for v in violations} >= {"N6", "N13"}


def test_risk_engine_uses_dominant_critical_dimension():
    risk = assess_risk(
        proposal(
            capability_id="tool.file_write",
            side_effect_class="destructive",
            reversibility="irreversible",
            data_classification="restricted",
        ),
        context(),
    )
    assert risk.aggregate_risk_class == "critical"
    assert risk.max_dimension_value >= 0.9


def test_unknown_risk_dimension_escalates_class():
    risk = assess_risk(proposal(data_classification="unknown", reversibility="unknown"), context(session_locality="unknown"))
    assert risk.unknown_dimensions
    assert risk.aggregate_risk_class in {"medium", "high", "critical"}
