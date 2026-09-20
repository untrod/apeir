import pytest

from nous_runtime.governance.contracts import ApprovalScope


@pytest.mark.parametrize(
    ("approved", "candidate", "expected"),
    [
        (ApprovalScope(workspace_path="/repo"), ApprovalScope(workspace_path="/repo"), True),
        (ApprovalScope(workspace_path="/repo"), ApprovalScope(workspace_path="/repo/src"), True),
        (ApprovalScope(workspace_path="/repo"), ApprovalScope(workspace_path="/repo2"), False),
        (ApprovalScope(cost_ceiling_usd=1.0), ApprovalScope(cost_ceiling_usd=0.5), True),
        (ApprovalScope(cost_ceiling_usd=1.0), ApprovalScope(cost_ceiling_usd=1.5), False),
        (ApprovalScope(token_ceiling=100), ApprovalScope(token_ceiling=50), True),
        (ApprovalScope(token_ceiling=100), ApprovalScope(token_ceiling=101), False),
        (ApprovalScope(execution_time_ceiling_ms=1000), ApprovalScope(execution_time_ceiling_ms=500), True),
        (ApprovalScope(execution_time_ceiling_ms=1000), ApprovalScope(execution_time_ceiling_ms=1500), False),
        (ApprovalScope(max_attempts=3), ApprovalScope(max_attempts=1), True),
        (ApprovalScope(max_attempts=3), ApprovalScope(max_attempts=4), False),
        (ApprovalScope(max_uses=2), ApprovalScope(max_uses=1), True),
        (ApprovalScope(max_uses=2), ApprovalScope(max_uses=3), False),
        (ApprovalScope(data_classification="internal"), ApprovalScope(data_classification="public"), True),
        (ApprovalScope(data_classification="internal"), ApprovalScope(data_classification="confidential"), False),
        (ApprovalScope(allowed_side_effect_classes=("read_only", "local_write")), ApprovalScope(allowed_side_effect_classes=("read_only",)), True),
        (ApprovalScope(allowed_side_effect_classes=("read_only",)), ApprovalScope(allowed_side_effect_classes=("local_write",)), False),
        (ApprovalScope(external_recipients=("local", "audit")), ApprovalScope(external_recipients=("local",)), True),
        (ApprovalScope(external_recipients=("local",)), ApprovalScope(external_recipients=("remote",)), False),
        (ApprovalScope(allowed_providers=("p1", "p2")), ApprovalScope(allowed_providers=("p1",)), True),
        (ApprovalScope(allowed_providers=("p1",)), ApprovalScope(allowed_providers=("p2",)), False),
        (ApprovalScope(allowed_models=("m1", "m2")), ApprovalScope(allowed_models=("m1",)), True),
        (ApprovalScope(allowed_models=("m1",)), ApprovalScope(allowed_models=("m2",)), False),
        (ApprovalScope(allowed_capabilities=("cap.a", "cap.b")), ApprovalScope(allowed_capabilities=("cap.a",)), True),
        (ApprovalScope(allowed_capabilities=("cap.a",)), ApprovalScope(allowed_capabilities=("cap.b",)), False),
        (ApprovalScope(action_id="a1"), ApprovalScope(action_id="a1"), True),
        (ApprovalScope(action_id="a1"), ApprovalScope(action_id="a2"), False),
        (ApprovalScope(proposal_hash="h1"), ApprovalScope(proposal_hash="h1"), True),
        (ApprovalScope(proposal_hash="h1"), ApprovalScope(proposal_hash="h2"), False),
        (ApprovalScope(provider_id="p1"), ApprovalScope(provider_id="p1"), True),
        (ApprovalScope(provider_id="p1"), ApprovalScope(provider_id="p2"), False),
        (ApprovalScope(model_id="m1"), ApprovalScope(model_id="m1"), True),
        (ApprovalScope(model_id="m1"), ApprovalScope(model_id="m2"), False),
        (ApprovalScope(node_id="n1"), ApprovalScope(node_id="n1"), True),
        (ApprovalScope(node_id="n1"), ApprovalScope(node_id="n2"), False),
        (ApprovalScope(deployment_channel="dev"), ApprovalScope(deployment_channel="dev"), True),
        (ApprovalScope(deployment_channel="dev"), ApprovalScope(deployment_channel="prod"), False),
    ],
)
def test_scope_subset_matrix(approved, candidate, expected):
    assert candidate.is_subset_of(approved) is expected
