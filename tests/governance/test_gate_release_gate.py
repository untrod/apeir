from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance.gate import ExecutionAuthorizationGate


class FailingStore:
    def __init__(self, fail):
        self.fail = fail

    def get_active_lease_for_proposal(self, proposal_hash, subject_id):
        return None

    def update_lease_status(self, lease_id, status):
        return True

    def save_proposal(self, data):
        return self.fail != "proposal"

    def save_decision(self, data):
        return self.fail != "decision"

    def save_audit(self, data):
        return self.fail != "audit"


def proposal(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "system.echo",
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "created_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return ActionProposal(**values)


def context():
    return AuthorizationContext(subject_type="user", subject_id="alice", authn_method="cli_os_user", authn_confidence=0.9)


def test_unknown_capability_requires_approval():
    # v0.2.0: unregistered capabilities are not denied outright — they get
    # a synthetic high-risk manifest and must go through approval.
    decision = ExecutionAuthorizationGate(store=FailingStore(fail="")).evaluate(
        proposal(capability_id="unknown.capability"),
        context(),
    )
    assert decision.action_mode == "ASK_APPROVAL"
    assert decision.reason_code == "APPROVAL_REQUIRED"


def test_proposal_hash_mismatch_is_denied():
    bad = proposal(proposal_hash="tampered")
    decision = ExecutionAuthorizationGate(store=FailingStore(fail="")).evaluate(bad, context())
    assert decision.action_mode == "DENY"
    assert decision.reason_code == "PROPOSAL_TAMPERED"


def test_missing_identity_is_denied():
    decision = ExecutionAuthorizationGate(store=FailingStore(fail="")).evaluate(
        proposal(),
        AuthorizationContext(subject_type="user", subject_id="", authn_confidence=0.9),
    )
    assert decision.action_mode == "DENY"
    assert decision.reason_code == "IDENTITY_MISSING"


def test_low_confidence_identity_is_denied():
    decision = ExecutionAuthorizationGate(store=FailingStore(fail="")).evaluate(
        proposal(),
        AuthorizationContext(subject_type="user", subject_id="alice", authn_confidence=0.1),
    )
    assert decision.action_mode == "DENY"
    assert decision.reason_code == "IDENTITY_LOW_CONFIDENCE"


def test_path_traversal_resource_is_denied():
    decision = ExecutionAuthorizationGate(store=FailingStore(fail="")).evaluate(
        proposal(affected_resources=("../outside",)),
        context(),
    )
    assert decision.action_mode == "DENY"
    assert "CONSTITUTION_VIOLATION" in decision.reason_code or decision.reason_code == "RESOURCE_PATH_TRAVERSAL"


def test_persistence_failures_are_denied(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    for fail in ("proposal", "decision", "audit"):
        decision = ExecutionAuthorizationGate(store=FailingStore(fail=fail)).evaluate(proposal(), context())
        assert decision.action_mode == "DENY"
        assert decision.reason_code.endswith("STORE_UNAVAILABLE")
