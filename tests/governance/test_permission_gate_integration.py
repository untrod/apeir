from nous_runtime.governance import (
    ActionProposal,
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceStore,
    PermissionEngine,
    PermissionRule,
)


def gate(tmp_path, monkeypatch, engine):
    value = ExecutionAuthorizationGate(
        GovernanceStore(tmp_path),
        permission_engine=engine,
    )
    monkeypatch.setattr(
        value,
        "_lookup_capability",
        lambda capability_id: {
            "capability_id": capability_id,
            "risk_level": "low",
        },
    )
    return value


def proposal():
    return ActionProposal(
        capability_id="device.camera",
        action_type="capability.execute",
        side_effect_class="read_only",
        reversibility="reversible",
        retry_behavior="idempotent",
        required_permissions=("camera.read",),
        affected_resources=("device:phone:camera",),
    )


def context():
    return AuthorizationContext(
        subject_type="agent",
        subject_id="agent:reviewer",
        authn_method="runtime",
        authn_confidence=1.0,
        session_locality="local",
    )


def test_gate_denies_missing_required_permission(tmp_path, monkeypatch):
    decision = gate(tmp_path, monkeypatch, PermissionEngine()).evaluate(
        proposal(), context()
    )
    assert decision.action_mode == "DENY"
    assert "PERMISSION_DENIED" in decision.reason_code


def test_gate_accepts_permission_before_normal_risk_policy(
    tmp_path, monkeypatch
):
    engine = PermissionEngine(
        (
            PermissionRule(
                "agent:*",
                "camera.read",
                "device:phone:*",
                context_equals={"locality": "local"},
            ),
        )
    )
    decision = gate(tmp_path, monkeypatch, engine).evaluate(
        proposal(), context()
    )
    assert "PERMISSION_DENIED" not in decision.reason_code
