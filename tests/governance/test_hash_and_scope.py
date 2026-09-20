from nous_runtime.governance.contracts import ActionProposal, ApprovalScope


def proposal(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "system.echo",
        "params": {"message": "hello", "nested": {"b": 2, "a": 1}},
        "target_node": "node-a",
        "target_workspace": "/repo",
        "target_project": "project-a",
        "target_work_item": "item-a",
        "affected_resources": ("/repo/file.txt",),
        "data_classification": "internal",
        "external_recipients": ("local",),
        "estimated_cost_usd": 0.01,
        "estimated_duration_ms": 100,
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "retry_behavior": "idempotent",
        "required_permissions": ("workspace.read",),
        "created_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-01T01:00:00Z",
    }
    values.update(overrides)
    return ActionProposal(**values)


def test_proposal_hash_is_stable_for_dict_order():
    a = proposal(params={"x": 1, "y": {"b": 2, "a": 1}})
    b = proposal(params={"y": {"a": 1, "b": 2}, "x": 1})
    assert a.proposal_hash == b.proposal_hash


def test_proposal_hash_changes_for_material_fields():
    base = proposal()
    variants = [
        proposal(action_type="workspace.write"),
        proposal(capability_id="tool.file_read"),
        proposal(params={"message": "changed"}),
        proposal(target_node="node-b"),
        proposal(target_workspace="/repo2"),
        proposal(target_project="project-b"),
        proposal(target_work_item="item-b"),
        proposal(affected_resources=("/repo/other.txt",)),
        proposal(data_classification="confidential"),
        proposal(external_recipients=("remote",)),
        proposal(estimated_cost_usd=0.02),
        proposal(side_effect_class="local_write"),
        proposal(reversibility="irreversible"),
        proposal(retry_behavior="unsafe"),
        proposal(required_permissions=("workspace.write",)),
        proposal(expires_at="2026-01-01T02:00:00Z"),
    ]
    for item in variants:
        assert item.proposal_hash != base.proposal_hash


def test_scope_rejects_path_prefix_sibling_expansion():
    approved = ApprovalScope(workspace_path="/tmp/nous/repo")
    sibling = ApprovalScope(workspace_path="/tmp/nous/repository")
    assert not sibling.is_subset_of(approved)


def test_scope_allows_equal_and_child_paths():
    approved = ApprovalScope(workspace_path="/tmp/nous/repo")
    assert ApprovalScope(workspace_path="/tmp/nous/repo").is_subset_of(approved)
    assert ApprovalScope(workspace_path="/tmp/nous/repo/subdir").is_subset_of(approved)


def test_scope_rejects_cost_and_side_effect_expansion():
    approved = ApprovalScope(cost_ceiling_usd=1.0, allowed_side_effect_classes=("read_only",))
    expanded = ApprovalScope(cost_ceiling_usd=2.0, allowed_side_effect_classes=("local_write",))
    assert not expanded.is_subset_of(approved)


def test_zero_cost_scope_is_restrictive():
    approved = ApprovalScope(cost_ceiling_usd=0.0)
    expanded = ApprovalScope(cost_ceiling_usd=0.01)
    assert not expanded.is_subset_of(approved)
