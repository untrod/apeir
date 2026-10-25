"""Real canonical Runtime/Store/Governance adapter tests; no mock Workflow executor."""

from tests.control_plane.test_human_sessions import human_env as human_env
from copy import deepcopy

import pytest

from nous_runtime.api import routes
from nous_runtime.api.workflow_routes import validate_definition
from nous_runtime.governance import (
    ExecutionAuthorizationGate,
    GovernanceStore,
    PermissionEngine,
    PermissionRule,
)
from nous_runtime.governance.contracts import ApprovalResponse, ActionProposal
from nous_runtime.governance.lease import LeaseManager
from nous_runtime.workflow.models import definition_from_dict, definition_to_dict


def spec(*steps):
    return {
        "workflow_id": "studio.test",
        "version": "1.0.0",
        "trigger": "manual",
        "steps": list(steps)
        or [
            {
                "step_id": "a",
                "step_type": "transform",
                "params": {"value": "actual-output"},
            }
        ],
    }


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_API_TOKEN", "FAKE_ONLY_WORKFLOW_STUDIO")
    store = GovernanceStore(tmp_path / ".nous")
    gate = ExecutionAuthorizationGate(
        store,
        permission_engine=PermissionEngine(
            (
                PermissionRule(
                    "api-service",
                    "workspace.read",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
                PermissionRule(
                    "api-service",
                    "workspace.write",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
                PermissionRule(
                    "api-service",
                    "workflow.execute",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
            )
        ),
    )
    # Capabilities are actual existing registry entries owned by this test host.
    from nous_runtime.compat.capability import register_capability

    register_capability(
        "project.read_file",
        risk="low",
        requires_auth=False,
        side_effect_class="read_only",
        reversibility="reversible",
        locality="local",
        idempotent=True,
        model_uncertainty=0,
    )
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    from nous_runtime.governance.broker import ApprovalBroker

    broker = ApprovalBroker(store=store)
    monkeypatch.setattr("nous_runtime.governance.broker.get_broker", lambda: broker)

    def call(method, path, body=None, *, approve=False, auth=True):
        result = routes.route_server(
            method,
            path,
            body=body,
            auth={"token": "FAKE_ONLY_WORKFLOW_STUDIO", "loopback": True}
            if auth
            else None,
        )
        if approve and result.get("error", {}).get("code") == "NOUS_APPROVAL_REQUIRED":
            # Trusted test approver issues a one-use lease for this exact recorded
            # proposal. Neither body fields nor the service caller can approve it.
            pending = next(
                item
                for item in broker.get_pending()
                if item["request_id"]
                == result["error"]["details"]["approval_request_id"]
            )
            proposal = ActionProposal.from_dict(
                store.get_proposal(pending["proposal_hash"])
            )
            LeaseManager(store).issue(
                proposal,
                ApprovalResponse(
                    request_id=pending["request_id"],
                    proposal_hash=proposal.proposal_hash,
                    decision="APPROVED",
                    approver_id="test-host-owner",
                ),
                subject_id="api-service",
            )
            result = routes.route_server(
                method,
                path,
                body=body,
                auth={"token": "FAKE_ONLY_WORKFLOW_STUDIO", "loopback": True},
            )
        return result

    return call, gate, tmp_path


def test_real_registration_execution_history_and_restart(api, monkeypatch):
    call, gate, root = api
    definition = spec()
    assert call("POST", "/api/v1/workflow/validate", {"definition": definition})[
        "data"
    ]["runnable"]
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": definition}, approve=True
    )["ok"]
    body = {
        "workflow_id": definition["workflow_id"],
        "version": "1.0.0",
        "inputs": {"x": 3},
        "idempotency_key": "original-one",
        "definition": definition,
    }
    completed = call("POST", "/api/v1/workflow/run", body, approve=True)
    assert completed["ok"], completed
    run = completed["data"]
    assert (
        run["state"] == "completed" and run["outputs"]["a"]["value"] == "actual-output"
    )
    assert run["execution_scope"] == "runtime-service"
    # Reconstruct both authorities; original Store/checkpoint/events survive.
    restored = ExecutionAuthorizationGate(
        GovernanceStore(root / ".nous"), permission_engine=gate.permission_engine
    )
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: restored)
    detail = call("GET", f"/api/v1/workflow/runs/{run['run_id']}")["data"]
    assert detail["run"]["run_id"] == run["run_id"]
    assert detail["events"] and detail["run"]["definition_digest"]
    repeated = call("POST", "/api/v1/workflow/run", body, approve=True)
    assert repeated["data"]["run_id"] == run["run_id"]
    catalog = call("GET", "/api/v1/workflow")["data"]
    assert len(catalog["runs"]) == 1
    assert "outputs" not in catalog["runs"][0]
    assert "definition" not in catalog["definitions"][0]
    restored_definition = call("GET", "/api/v1/workflow/definitions/studio.test/1.0.0")[
        "data"
    ]["definition"]
    assert restored_definition == definition_to_dict(definition_from_dict(definition))


def test_unauthenticated_permission_denied_and_actual_workspace_binding(api):
    call, gate, root = api
    assert not call("GET", "/api/v1/workflow", auth=False)["ok"]
    denied = call(
        "POST",
        "/api/v1/workflow/register",
        {"definition": spec(), "workspace": "/wrong-target"},
    )
    assert not denied["ok"]
    from nous_runtime.governance.broker import get_broker

    pending = get_broker().get_pending()
    proposal = gate.store.get_proposal(pending[-1]["proposal_hash"])
    assert proposal["target_workspace"] == str(root)
    assert proposal["affected_resources"] == [str(root / ".nous" / "workflows.db")]
    assert not (root / ".nous" / "workflows.db").exists()
    gate.permission_engine = PermissionEngine()
    assert not call("GET", "/api/v1/workflow")["ok"]


def test_approval_cannot_be_supplied_in_inputs_or_resume_and_cancel_is_durable(api):
    call, _, _ = api
    definition = spec({"step_id": "review", "step_type": "approval"})
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": definition}, approve=True
    )["ok"]
    payload = {
        "workflow_id": "studio.test",
        "version": "1.0.0",
        "inputs": {},
        "idempotency_key": "waiting",
    }
    waiting = call("POST", "/api/v1/workflow/run", payload, approve=True)["data"]
    assert waiting["state"] == "waiting_approval"
    path = f"/api/v1/workflow/runs/{waiting['run_id']}/action"
    still = call("POST", path, {"action": "resume"}, approve=True)
    assert still["data"]["state"] == "waiting_approval"
    assert not call(
        "POST", path, {"action": "resume", "approved_steps": ["review"]}, approve=True
    )["ok"]
    injected = {
        **payload,
        "idempotency_key": "injected",
        "inputs": {"_approved_steps": ["review"]},
    }
    assert not call("POST", "/api/v1/workflow/run", injected, approve=True)["ok"]
    assert (
        call("POST", path, {"action": "cancel"}, approve=True)["data"]["state"]
        == "cancelled"
    )
    assert (
        call("POST", path, {"action": "resume"}, approve=True)["data"]["state"]
        == "cancelled"
    )


def test_registered_version_cannot_be_silently_replaced_or_run_from_a_different_draft(
    api,
):
    call, _, _ = api
    original = spec()
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": original}, approve=True
    )["ok"]
    changed = deepcopy(original)
    changed["steps"][0]["params"]["value"] = "other"
    assert not call(
        "POST", "/api/v1/workflow/register", {"definition": changed}, approve=True
    )["ok"]
    result = call(
        "POST",
        "/api/v1/workflow/run",
        {
            "workflow_id": "studio.test",
            "version": "1.0.0",
            "inputs": {},
            "definition": changed,
            "idempotency_key": "mismatch",
        },
        approve=True,
    )
    assert not result["ok"] and "differs" in result["error"]["message"]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(unknown=True),
        lambda d: d["steps"].append(deepcopy(d["steps"][0])),
        lambda d: d["steps"][0].update(depends_on=["missing"]),
        lambda d: d["steps"][0].update(depends_on=["a"]),
        lambda d: d["steps"][0].update(timeout_seconds=float("inf")),
        lambda d: d["steps"][0].update(retries=True),
        lambda d: d["steps"][0].update(approval_required="false"),
        lambda d: d["steps"][0].update(step_type="capability", action=""),
    ],
)
def test_strict_admission_retains_canonical_dag_validation(change):
    definition = spec()
    change(definition)
    with pytest.raises((TypeError, ValueError)):
        validate_definition(definition)


def test_all_enums_are_not_claimed_executable(api):
    call, _, _ = api
    definition = spec({"step_id": "shell", "step_type": "command", "action": "echo"})
    result = call("POST", "/api/v1/workflow/validate", {"definition": definition})
    assert result["data"]["valid"] and not result["data"]["runnable"]
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": definition}, approve=True
    )["ok"]
    result = call(
        "POST",
        "/api/v1/workflow/run",
        {
            "workflow_id": "studio.test",
            "version": "1.0.0",
            "idempotency_key": "unsupported",
        },
        approve=True,
    )
    assert result["error"]["code"] == "NOUS_NOT_AVAILABLE"
    assert (
        definition_to_dict(definition_from_dict(definition))["steps"][0]["action"]
        == "echo"
    )


def test_step_approval_requires_current_nonserialized_human_and_original_scope(
    human_env, tmp_path, monkeypatch
):
    from tests.control_plane.test_human_sessions import login
    from nous_runtime.api.workflow_routes import handle_workflow_run_action
    from nous_runtime.workflow import WorkflowRuntime
    from nous_runtime.governance.contracts import AuthorizationContext
    from nous_runtime.governance.permission import PermissionEngine, PermissionRule
    from nous_runtime.compat.capability import register_capability

    gate, auth, client, _ = human_env
    issued, context = login(auth, client)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    register_capability(
        "project.read_file",
        risk="low",
        requires_auth=False,
        side_effect_class="read_only",
        reversibility="reversible",
        locality="local",
        idempotent=True,
        model_uncertainty=0,
    )
    runtime = WorkflowRuntime(str(tmp_path))
    definition = definition_from_dict(
        spec(
            {"step_id": "review", "step_type": "approval"},
            {
                "step_id": "after",
                "step_type": "transform",
                "depends_on": ["review"],
                "params": {"value": "approved-output"},
            },
        )
    )
    runtime.register(definition)
    waiting = runtime.start(definition.workflow_id, definition.version)
    body = {
        "action": "approve",
        "step_id": "review",
        "definition_digest": waiting.definition_digest,
    }
    resource = f"workflow:{waiting.run_id}:review"
    with pytest.raises(PermissionError):
        handle_workflow_run_action(waiting.run_id, body, authorization_context=context)
    auth.permissions = PermissionEngine(
        (PermissionRule(context.subject_id, "governance.approve", resource),)
    )
    reconstructed = AuthorizationContext.from_dict(context.to_dict())
    with pytest.raises(PermissionError):
        handle_workflow_run_action(
            waiting.run_id, body, authorization_context=reconstructed
        )
    mismatch = handle_workflow_run_action(
        waiting.run_id,
        {**body, "definition_digest": "wrong"},
        authorization_context=context,
    )
    assert not mismatch["ok"]
    completed = handle_workflow_run_action(
        waiting.run_id, body, authorization_context=context
    )
    assert completed["data"]["state"] == "completed"
    assert completed["data"]["outputs"]["after"]["value"] == "approved-output"
    assert any(
        item["event_type"] == "workflow.approval.accepted"
        for item in gate.store.operation_audit()
    )
    auth.logout(context)
    with pytest.raises(PermissionError):
        handle_workflow_run_action(waiting.run_id, body, authorization_context=context)


def test_uncertain_original_host_can_be_cancelled_without_replaying_or_claiming_success(
    api,
):
    from nous_runtime.workflow import WorkflowRuntime

    call, _, root = api
    effects = []

    def response_lost(step, context):
        effects.append(context["run_id"])
        raise RuntimeError("qualification response lost after recorded test effect")

    definition = definition_from_dict(
        spec(
            {
                "step_id": "effect",
                "step_type": "capability",
                "action": "qualification.effect",
            }
        )
    )
    original_host = WorkflowRuntime(
        str(root), handlers={"qualification.effect": response_lost}
    )
    original_host.register(definition)
    original = original_host.start(
        definition.workflow_id, definition.version, idempotency_key="uncertain-original"
    )
    assert original.state.value == "unknown" and effects == [original.run_id]
    detail = call("GET", f"/api/v1/workflow/runs/{original.run_id}")
    assert detail["data"]["run"]["state"] == "unknown"
    path = f"/api/v1/workflow/runs/{original.run_id}/action"
    resumed = call("POST", path, {"action": "resume"}, approve=True)
    assert resumed["error"]["code"] == "NOUS_NOT_AVAILABLE"
    cancelled = call("POST", path, {"action": "cancel"}, approve=True)
    assert cancelled["ok"], cancelled
    assert cancelled["data"]["state"] == "unknown"
    assert cancelled["data"]["cancellation_requested"] is True
    assert effects == [original.run_id]
    assert original_host.resume(original.run_id).state.value == "unknown"
    assert effects == [original.run_id]


def test_history_summary_does_not_bypass_original_identity_validation(api):
    import sqlite3
    from nous_runtime.workflow import WorkflowRuntime
    from nous_runtime.workflow.store import WorkflowBindingError

    _, _, root = api
    runtime = WorkflowRuntime(str(root))
    definition = definition_from_dict(spec())
    runtime.register(definition)
    run = runtime.start(definition.workflow_id, definition.version)
    with sqlite3.connect(runtime.store.path) as db:
        db.execute(
            "UPDATE workflow_runs SET state='unknown' WHERE run_id=?", (run.run_id,)
        )
    with pytest.raises(WorkflowBindingError):
        runtime.store.list_run_summaries()
