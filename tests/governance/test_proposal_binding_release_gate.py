import pytest

from nous_runtime.governance.contracts import ActionProposal


def proposal(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "model.reason",
        "provider_id": "provider-a",
        "model_id": "model-a",
        "agent_id": "agent-a",
        "deployment_channel": "development",
        "locality": "local",
        "params": {"prompt": "hello"},
        "target_node": "node-a",
        "target_workspace": "/workspace",
        "target_project": "project-a",
        "target_work_item": "work-a",
        "affected_resources": ("/workspace/a.txt",),
        "data_classification": "internal",
        "external_recipients": ("local",),
        "estimated_cost_usd": 0.01,
        "estimated_duration_ms": 100,
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "retry_behavior": "idempotent",
        "required_permissions": ("model.invoke",),
        "created_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-01T01:00:00Z",
    }
    values.update(overrides)
    return ActionProposal(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_type", "provider.execute"),
        ("capability_id", "model.code"),
        ("provider_id", "provider-b"),
        ("model_id", "model-b"),
        ("agent_id", "agent-b"),
        ("deployment_channel", "production"),
        ("locality", "remote"),
        ("target_node", "node-b"),
        ("target_workspace", "/other"),
        ("target_project", "project-b"),
        ("target_work_item", "work-b"),
        ("affected_resources", ("/workspace/b.txt",)),
        ("data_classification", "confidential"),
        ("external_recipients", ("remote",)),
        ("estimated_cost_usd", 0.02),
        ("estimated_duration_ms", 200),
        ("side_effect_class", "external_write"),
        ("reversibility", "irreversible"),
        ("retry_behavior", "unsafe"),
        ("required_permissions", ("network",)),
        ("expires_at", "2026-01-01T02:00:00Z"),
    ],
)
def test_material_authorization_fields_change_proposal_hash(field, value):
    base = proposal()
    changed = proposal(**{field: value})
    assert changed.proposal_hash != base.proposal_hash


def test_provider_model_agent_roundtrip():
    original = proposal()
    restored = ActionProposal.from_dict(original.to_dict())
    assert restored.provider_id == original.provider_id
    assert restored.model_id == original.model_id
    assert restored.agent_id == original.agent_id
    assert restored.deployment_channel == original.deployment_channel
    assert restored.locality == original.locality
    assert restored.proposal_hash == original.proposal_hash
