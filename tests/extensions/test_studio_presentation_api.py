"""Real Gate, Broker, Registry and Runtime routing for the restricted UI host."""

import json
from pathlib import Path

import pytest

from nous_runtime.api import routes
from nous_runtime.governance import (
    ExecutionAuthorizationGate,
    GovernanceStore,
    PermissionEngine,
    PermissionRule,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context, _subject_id

EXAMPLE = (
    Path(__file__).parents[2]
    / "examples"
    / "studio_system_monitor"
    / "nous.extension.json"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_API_TOKEN", "APEIR_FAKE_ONLY_UI_HOST_QUALIFICATION")
    resource = str(tmp_path / ".nous" / "extensions" / "registry.json")
    gate = ExecutionAuthorizationGate(
        GovernanceStore(tmp_path / ".nous"),
        permission_engine=PermissionEngine(
            (
                PermissionRule(_subject_id(), "governance.approve", resource),
                PermissionRule(
                    _subject_id(),
                    "governance.approve",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
                PermissionRule(
                    "api-service",
                    "workspace.read",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
                PermissionRule(
                    "api-service",
                    "workflow.execute",
                    str(tmp_path / ".nous" / "workflows.db"),
                ),
            )
            + tuple(
                PermissionRule("api-service", permission, resource)
                for permission in (
                    "workspace.read",
                    "workspace.write",
                    "workflow.execute",
                )
            )
        ),
    )
    broker = ApprovalBroker(gate.store)
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr("nous_runtime.governance.broker.get_broker", lambda: broker)
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

    def call(
        method, path, body=None, params=None, *, approve=False, authenticated=True
    ):
        auth = (
            {"token": "APEIR_FAKE_ONLY_UI_HOST_QUALIFICATION", "loopback": True}
            if authenticated
            else None
        )
        result = routes.route_server(method, path, body=body, params=params, auth=auth)
        if approve and result.get("error", {}).get("code") == "NOUS_APPROVAL_REQUIRED":
            broker.respond_legacy(
                result["error"]["details"]["approval_request_id"],
                "approve",
                _build_context(),
                gate=gate,
            )
            result = routes.route_server(
                method, path, body=body, params=params, auth=auth
            )
        return result

    return call, gate, tmp_path


def source():
    return EXAMPLE.read_text(encoding="utf-8")


def installed(call):
    review = call(
        "POST", "/api/v1/studio/extensions/review", {"source_manifest": source()}
    )
    assert review["ok"], review
    binding = review["data"]
    result = call(
        "POST",
        "/api/v1/studio/extensions/install",
        {
            "source_manifest": source(),
            "expected_digest": binding["digest"],
            "expected_previous_digest": binding["previous_digest"],
        },
        approve=True,
    )
    assert result["ok"], result
    return result["data"]


def configure(call, record, enabled=True):
    return call(
        "POST",
        "/api/v1/studio/extensions/configure",
        {
            "extension_id": record["extension_id"],
            "enabled": enabled,
            "expected_digest": record["digest"],
            "expected_version": record["version"],
        },
        approve=True,
    )


def test_api_lifecycle_requires_authentication_permissions_and_exact_package(
    client, monkeypatch
):
    call, gate, _ = client
    assert not call("GET", "/api/v1/studio/extensions", authenticated=False)["ok"]
    record = installed(call)
    assert record["enabled"] is False and record["authority"] == "none"
    component = record["contributions"][1]["type"]
    params = {
        "component_type": component,
        "expected_digest": record["digest"],
        "source": "runtime.status",
    }
    assert not call("GET", "/api/v1/studio/extensions/data", params=params)["ok"]
    assert configure(call, record)["data"]["enabled"]
    from nous_runtime.extensions.presentation import StudioExtensionHost

    monkeypatch.setattr(
        StudioExtensionHost,
        "_status",
        staticmethod(lambda: {"running": True, "version": "qualification-only"}),
    )
    read = call("GET", "/api/v1/studio/extensions/data", params=params)
    assert read["data"]["values"]["running"] is True
    assert not call(
        "GET",
        "/api/v1/studio/extensions/data",
        params={**params, "source": "credential.store"},
    )["ok"]
    assert configure(call, record, False)["data"]["enabled"] is False
    assert not call("GET", "/api/v1/studio/extensions/data", params=params)["ok"]
    assert configure(call, record)["ok"]
    assert call(
        "POST",
        "/api/v1/studio/extensions/remove",
        {
            "extension_id": record["extension_id"],
            "expected_digest": record["digest"],
            "expected_version": record["version"],
        },
        approve=True,
    )["data"]["removed"]
    assert call("GET", "/api/v1/studio/extensions")["data"]["extensions"] == []
    gate.permission_engine = PermissionEngine()
    assert not call("GET", "/api/v1/studio/extensions")["ok"]


def test_original_governance_summary_binds_digest_without_raw_manifest_or_body_workspace(
    client,
    monkeypatch,
):
    call, gate, root = client
    proposals = []
    evaluate = gate.evaluate

    def capture(proposal, context):
        proposals.append(proposal)
        return evaluate(proposal, context)

    monkeypatch.setattr(gate, "evaluate", capture)
    value = json.loads(source())
    value["description"] = "PRIVATE_REVIEW_DESCRIPTION_NOT_AN_AUDIT_FIELD"
    text = json.dumps(value)
    reviewed = call(
        "POST", "/api/v1/studio/extensions/review", {"source_manifest": text}
    )["data"]
    body = {
        "source_manifest": text,
        "expected_digest": reviewed["digest"],
        "expected_previous_digest": "",
    }
    pending = call("POST", "/api/v1/studio/extensions/install", body)
    assert pending["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    request_id = pending["error"]["details"]["approval_request_id"]
    request = gate.store.get_approval_request(request_id)
    proposal = gate.store.get_proposal(request["proposal_hash"])
    assert "PRIVATE_REVIEW_DESCRIPTION" not in json.dumps(proposal)
    original = next(p for p in proposals if p.capability_id == "extension.ui.install")
    assert "source_manifest" not in original.params["body"]
    assert original.params["body"]["package_digest"] == reviewed["digest"]
    assert proposal["parameter_hash"] == original.to_dict()["parameter_hash"]
    assert proposal["target_workspace"] == str(root)
    denied = call(
        "POST",
        "/api/v1/studio/extensions/install",
        {**body, "workspace": "/another-root"},
    )
    assert not denied["ok"]
    assert not (root / ".nous" / "extensions" / "registry.json").exists()


def test_studio_widget_cannot_select_unrequested_actions_or_bypass_disabled_state(
    client,
):
    call, _, _ = client
    record = installed(call)
    assert configure(call, record)["ok"]
    widget = record["contributions"][1]["type"]
    action = {
        "component_type": widget,
        "expected_digest": record["digest"],
        "action": "workflow.run",
        "idempotency_key": "original-widget-action",
    }
    assert not call("POST", "/api/v1/studio/extensions/action", action, approve=True)[
        "ok"
    ]
    assert not call(
        "POST", "/api/v1/studio/extensions/action", {**action, "action": "host.shell"}
    )["ok"]
    assert configure(call, record, False)["ok"]
    assert not call("POST", "/api/v1/studio/extensions/action", action, approve=True)[
        "ok"
    ]


def test_declared_workflow_action_still_needs_original_gate_permission_and_lease(
    client,
):
    from nous_runtime.workflow import (
        WorkflowDefinition,
        WorkflowRuntime,
        WorkflowStep,
        StepType,
        TriggerType,
    )
    from tests.extensions.test_studio_presentation import action_manifest

    call, gate, root = client
    runtime = WorkflowRuntime(str(root))
    runtime.register(
        WorkflowDefinition(
            "monitor.reference",
            "1.0.0",
            TriggerType.MANUAL,
            (
                WorkflowStep(
                    "result", StepType.TRANSFORM, params={"value": "actual pure result"}
                ),
            ),
        )
    )
    raw = json.dumps(action_manifest())
    review = call("POST", "/api/v1/studio/extensions/review", {"source_manifest": raw})[
        "data"
    ]
    record = call(
        "POST",
        "/api/v1/studio/extensions/install",
        {
            "source_manifest": raw,
            "expected_digest": review["digest"],
            "expected_previous_digest": "",
        },
        approve=True,
    )["data"]
    assert configure(call, record)["ok"]
    body = {
        "component_type": record["contributions"][1]["type"],
        "expected_digest": record["digest"],
        "action": "workflow.run",
        "idempotency_key": "approved-original-widget-key",
    }
    pending = call("POST", "/api/v1/studio/extensions/action", body)
    assert pending["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    original_request = gate.store.get_approval_request(
        pending["error"]["details"]["approval_request_id"]
    )
    original_proposal = gate.store.get_proposal(original_request["proposal_hash"])
    assert original_proposal["affected_resources"] == [
        str(root / ".nous" / "workflows.db")
    ]
    assert runtime.store.list_runs() == []
    first = call("POST", "/api/v1/studio/extensions/action", body, approve=True)
    assert first["ok"], first
    result = first["data"]
    assert result["state"] == "completed"
    assert result["outputs"]["result"]["value"] == "actual pure result"
    repeated = call("POST", "/api/v1/studio/extensions/action", body, approve=True)
    assert repeated["data"]["run_id"] == result["run_id"]
    assert len(runtime.store.list_runs()) == 1
    gate.permission_engine = PermissionEngine()
    denied = call(
        "POST",
        "/api/v1/studio/extensions/action",
        {**body, "idempotency_key": "after-revocation"},
    )
    assert not denied["ok"]
    assert len(runtime.store.list_runs()) == 1
