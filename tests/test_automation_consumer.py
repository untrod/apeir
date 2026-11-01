"""Automation consumes original Workflow/Work authority and evidence."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from threading import Thread, Event, local

import pytest

from nous_runtime.api.desktop_routes import (
    handle_automations_add,
    handle_automations_action,
)
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.events import EventStream
from nous_runtime.governance import (
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceStore,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.workflow.automation import AutomationConsumer
from nous_runtime.workflow.store import WorkflowBindingError, WorkflowStore
from tests.control_plane.test_human_sessions import (
    human_env as human_env_fixture,
    login,
)

human_env = human_env_fixture
FAKE_SERVICE_TOKEN = "fake-automation-service-token"


@pytest.fixture
def consumer(tmp_path):
    service = AutomationConsumer(
        tmp_path, gate=ExecutionAuthorizationGate(GovernanceStore(tmp_path / ".nous"))
    )
    service.admit_management(_build_context())
    return service


def prepare(consumer):
    binding = consumer.add_simulation(name="Governed simulated firmware")
    pending = consumer.trigger(binding["id"], "original")
    assert pending["state"] == "waiting_approval", pending
    assert pending["effect_counts"][pending["outputs"]["mutate"]["work_id"]] == 0
    return binding, pending


def approve(consumer, pending):
    return ApprovalBroker(consumer.gate.store).approve_operation_once(
        pending["outputs"]["mutate"]["approval_request_id"],
        _build_context(),
        gate=consumer.gate,
    )


def test_original_work_matches_only_after_human_approval_and_independent_observation(
    consumer,
):
    from nous_runtime.core.redaction import redact_sensitive_text

    started = time.monotonic()
    binding, pending = prepare(consumer)
    prepared = time.monotonic()
    work_id = pending["outputs"]["mutate"]["work_id"]
    authorization_id = pending["works"][-1]["execution_arguments"]["authorization_id"]
    request = consumer.gate.get_operation_request(authorization_id)
    assert request.work_id == request.operation_id == work_id
    assert request.workflow_run_id == pending["run_id"]
    approval = ApprovalBroker(consumer.gate.store).get_operation_approval(
        pending["outputs"]["mutate"]["approval_request_id"], gate=consumer.gate
    )
    assert approval["governance_request_id"] == authorization_id
    assert approval["proposal_hash"] == authorization_id
    approve(consumer, pending)
    approved = time.monotonic()
    completed = consumer.resume(binding["id"], pending["run_id"])
    resumed = time.monotonic()
    # Keep the successful-path assertion strict. A failed run must expose its
    # existing state/error without dumping credentials, raw evidence or params.
    assert completed["state"] == "completed", json.dumps(
        {
            "run_id": completed["run_id"],
            "state": completed["state"],
            "error": redact_sensitive_text(str(completed.get("error", "")))[:2000],
            "step_states": completed["step_states"],
            "reconciliation_required": completed["reconciliation_required"],
            "effect_counts": completed["effect_counts"],
            "elapsed_ms": {
                "prepare": round((prepared - started) * 1000, 3),
                "approval": round((approved - prepared) * 1000, 3),
                "resume": round((resumed - approved) * 1000, 3),
            },
            "works": [
                {
                    "work_id": work["work_id"],
                    "state": work["state"],
                    "assigned_node": work.get("assigned_node"),
                    "receipt_present": bool(
                        work.get("result_summary", {}).get("remote_execution_receipt")
                    ),
                    "verdict": work.get("effect_verification", {}).get("verdict"),
                }
                for work in completed["works"]
            ],
        },
        sort_keys=True,
    )
    mutation = completed["outputs"]["mutate"]
    assert mutation["work_id"] == pending["outputs"]["mutate"]["work_id"]
    assert mutation["state"] == "COMMITTED"
    assert mutation["effect_verification"]["verdict"] == "MATCH"
    assert mutation["receipt"]["operation_id"] == mutation["work_id"]
    assert mutation["receipt"]["signed_envelope_digest"]
    assert mutation["observations"]
    assert completed["effect_counts"][mutation["work_id"]] == 1
    assert completed["simulated"] is True
    assert completed["kernel_traversed"] is False
    cas = ContentAddressedArtifactStore(consumer.controller_state / "artifacts")
    for work in completed["works"]:
        for ref in (
            work["input_artifacts"] + work["output_artifacts"] + work["evidence_refs"]
        ):
            assert cas.verify("sha256:" + ref.removeprefix("artifact://sha256/"))
    assert (
        EventStream(str(consumer.root)).get_run(completed["run_id"]).state.value
        == "COMPLETED"
    )
    history = consumer.history(binding["id"])
    assert history["total"] == 1
    assert history["history"][0]["run"]["run_id"] == pending["run_id"]
    assert (
        history["history"][0]["works"][-1]["effect_verification"]["verdict"] == "MATCH"
    )


def test_duplicate_concurrent_trigger_and_restart_reuse_the_original_run(consumer):
    binding = consumer.add_simulation(name="Only one original trigger")
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(
            executor.map(lambda _: consumer.trigger(binding["id"], "same"), range(2))
        )
    assert runs[0]["run_id"] == runs[1]["run_id"]
    assert len(consumer.store.automation_history(binding["id"])) == 1
    original_work_id = runs[0]["outputs"]["mutate"]["work_id"]
    approve(consumer, runs[0])
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    # Repeated scheduler/manual delivery cannot turn an approval into execution.
    duplicate = restarted.trigger(binding["id"], "same")
    assert duplicate["state"] == "waiting_approval"
    completed = restarted.resume(binding["id"], runs[0]["run_id"])
    assert completed["state"] == "completed"
    assert completed["outputs"]["mutate"]["work_id"] == original_work_id
    assert completed["effect_counts"][original_work_id] == 1
    next_run = restarted.trigger(binding["id"], "new-explicit-trigger")
    assert next_run["state"] == "waiting_approval"
    assert next_run["run_id"] != completed["run_id"]
    assert next_run["outputs"]["mutate"]["work_id"] != original_work_id
    assert (
        next_run["outputs"]["mutate"]["approval_request_id"]
        != runs[0]["outputs"]["mutate"]["approval_request_id"]
    )


def test_simulation_factory_keeps_the_original_governance_and_mints_no_authority(
    consumer,
):
    from nous_runtime.reality.preview import create_automation_simulation_components

    def authority_counts():
        with consumer.gate.store.operation_transaction() as db:
            return tuple(
                db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "governance_leases",
                    "governance_approval_requests",
                    "governance_approval_responses",
                    "governance_lease_consumption",
                )
            )

    before = authority_counts()
    assert before == (0, 0, 0, 0)
    components = create_automation_simulation_components(
        consumer.root, governance=consumer.gate
    )
    try:
        assert components.gate is consumer.gate
        assert components.handler.governance is consumer.gate
        assert authority_counts() == before
        assert components.server.pending == {}
        assert components.provider.execution_count("unapproved-work") == 0
    finally:
        asyncio.run(components.close())


@pytest.mark.parametrize("authority", ["missing", "another-workspace"])
def test_simulation_factory_rejects_missing_or_replacement_authority(
    consumer, authority
):
    from nous_runtime.reality.preview import create_automation_simulation_components

    gate = (
        None
        if authority == "missing"
        else ExecutionAuthorizationGate(
            GovernanceStore(consumer.root / "other" / ".nous")
        )
    )
    with pytest.raises(ValueError, match="original workspace Governance"):
        create_automation_simulation_components(consumer.root, governance=gate)
    assert not (consumer.root / ".nous" / "automation-simulation").exists()


def test_cancelled_approval_run_cannot_resume_after_restart_or_later_approval(consumer):
    binding, pending = prepare(consumer)
    assert consumer.cancel(binding["id"], pending["run_id"])["state"] == "cancelled"
    with pytest.raises(PermissionError):
        approve(consumer, pending)
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    resumed = restarted.resume(binding["id"], pending["run_id"])
    assert resumed["cancellation_requested"]
    assert resumed["state"] == "cancelled"
    assert resumed["works"][-1]["state"] == "CREATED"
    assert restarted.trigger(binding["id"], "original")["run_id"] == pending["run_id"]


@pytest.mark.parametrize("authority", ["expired", "revoked", "denied"])
def test_original_authority_is_revalidated_before_dispatch(consumer, authority):
    binding, pending = prepare(consumer)
    broker = ApprovalBroker(consumer.gate.store)
    request_id = pending["outputs"]["mutate"]["approval_request_id"]
    if authority == "denied":
        broker.deny_operation(request_id, _build_context(), gate=consumer.gate)
    else:
        approve(consumer, pending)
        with consumer.gate.store.operation_transaction() as db:
            row = db.execute(
                "SELECT lease_id,lease_json FROM governance_leases ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            lease_id = row[0]
            if authority == "expired":
                value = json.loads(row[1])
                value["expires_at"] = "2000-01-01T00:00:00Z"
                db.execute(
                    "UPDATE governance_leases SET expires_at=?,lease_json=? WHERE lease_id=?",
                    (value["expires_at"], json.dumps(value), lease_id),
                )
        if authority == "revoked":
            authorization_id = pending["works"][-1]["execution_arguments"][
                "authorization_id"
            ]
            consumer.gate.revoke_operation_authority(
                authorization_id, _build_context(), grant_id=lease_id
            )
    resumed = consumer.resume(binding["id"], pending["run_id"])
    assert resumed["state"] != "completed"
    assert resumed["effect_counts"][pending["outputs"]["mutate"]["work_id"]] == 0
    assert resumed["works"][-1]["state"] == "CREATED"


def test_one_shot_due_consumer_is_bounded_and_does_not_resume_prior_trigger(consumer):
    due_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    first = consumer.add_simulation(name="First due", trigger="schedule", due_at=due_at)
    second = consumer.add_simulation(
        name="Second due", trigger="schedule", due_at=due_at
    )
    assert len(consumer.run_due(limit=1)) == 1
    assert len(consumer.run_due(limit=1)) == 1
    assert consumer.run_due(limit=10) == []
    assert consumer.history(first["id"])["total"] == 1
    assert consumer.history(second["id"])["total"] == 1
    with pytest.raises(ValueError, match="between 1 and 10"):
        consumer.run_due(limit=11)
    with pytest.raises(ValueError, match="changed key"):
        consumer.trigger(first["id"], "not-original-due")


def test_immutable_definition_or_original_inputs_change_fails_closed(consumer):
    binding, pending = prepare(consumer)
    with consumer.store._db() as db:
        row = db.execute(
            "SELECT run_json FROM workflow_runs WHERE run_id=?", (pending["run_id"],)
        ).fetchone()
        changed = json.loads(row[0])
        changed["inputs"]["_agent_id"] = "other-agent"
        db.execute(
            "UPDATE workflow_runs SET run_json=? WHERE run_id=?",
            (json.dumps(changed), pending["run_id"]),
        )
    with pytest.raises(WorkflowBindingError):
        consumer.trigger(binding["id"], "original")
    with pytest.raises(WorkflowBindingError):
        consumer.resume(binding["id"], pending["run_id"])


def test_legacy_enabled_text_cannot_execute_and_body_authority_is_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    legacy = handle_automations_add(
        {"name": "Legacy", "action": "update firmware", "trigger": "schedule"}
    )
    assert legacy["data"]["qualification"] == "UNQUALIFIED"
    result = handle_automations_action(
        {
            "action": "trigger",
            "automation_id": legacy["data"]["id"],
            "trigger_key": "test",
        }
    )
    assert not result["ok"]
    assert result["error"]["code"] == "AUTOMATION_UNQUALIFIED"
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", None)
    forged = AuthorizationContext(
        subject_type="user",
        subject_id="forged-human",
        authn_method="cli_os_user",
        authn_confidence=1.0,
        session_locality="local",
    )
    with pytest.raises(PermissionError):
        handle_automations_add(
            {"adapter": "simulated-reality", "name": "Cannot self-approve"},
            authorization_context=forged,
        )
    forged_body = handle_automations_add(
        {
            "adapter": "simulated-reality",
            "name": "Cannot self-approve",
            "approved_steps": ["mutate"],
            "actor": "human",
        },
        authorization_context=_build_context(),
    )
    assert not forged_body["ok"]


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize(
    "start_ack", [True, False], ids=["start-recorded", "start-lost"]
)
def test_effect_then_response_loss_reconciles_original_receipt_without_another_effect(
    consumer, monkeypatch, cancel, start_ack
):
    from nous_runtime.node_runtime.relay import NodeRelayClient
    from nous_runtime.reality.preview import _DemoComponents, STABLE_ID
    from nous_runtime.reality import SimulationFault

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    work_id = pending["outputs"]["mutate"]["work_id"]
    recorded_start = Event()
    original_initialize = _DemoComponents._initialize
    original_send = NodeRelayClient._send

    async def control_start_ack(self, websocket, message_type, payload, **kwargs):
        if (
            message_type == "ACK"
            and payload.get("acknowledged") == "WORKLOAD_START"
            and payload.get("workload_id") == work_id
        ):
            if not start_ack:
                return  # Omit this notification, not the effect or its journal.
            await original_send(self, websocket, message_type, payload, **kwargs)
            # Isolate terminal-response loss from loss of the earlier start ACK.
            # This is a causal barrier, not a delay or a longer recovery bound.
            assert await asyncio.to_thread(recorded_start.wait, 5)
            return
        await original_send(self, websocket, message_type, payload, **kwargs)

    def inject_response_loss(self, *args, **kwargs):
        original_initialize(self, *args, **kwargs)
        original_mark = self.server._mark_work_running

        def record_start(acknowledged_work, node_id):
            original_mark(acknowledged_work, node_id)
            if acknowledged_work == work_id:
                recorded_start.set()

        monkeypatch.setattr(self.server, "_mark_work_running", record_start)
        self.response_loss = True
        self.provider.inject_fault(STABLE_ID, SimulationFault.EFFECT_THEN_RESPONSE_LOST)

    monkeypatch.setattr(NodeRelayClient, "_send", control_start_ack)
    monkeypatch.setattr(_DemoComponents, "_initialize", inject_response_loss)
    uncertain = consumer.resume(binding["id"], pending["run_id"])
    assert uncertain["state"] != "completed"
    assert uncertain["reconciliation_required"]
    assert uncertain["effect_counts"][work_id] == 1
    if start_ack:
        assert recorded_start.is_set()
        assert uncertain["works"][-1]["state"] == "RUNNING"
    else:
        assert not recorded_start.is_set()
        assert uncertain["works"][-1]["state"] == "ASSIGNED"
    assert not uncertain["works"][-1]["result_summary"].get("remote_execution_receipt")
    assert uncertain["works"][-1]["effect_verification"].get("verdict") != "MATCH"
    journal_path = (
        consumer.root / ".nous" / "automation-simulation" / "node" / "workloads.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))[work_id]
    assert journal["state"] == journal["receipt"]["result"] == "COMPLETED"
    assert journal["receipt"]["operation_id"] == work_id
    assert consumer.trigger(binding["id"], "original")["run_id"] == pending["run_id"]
    if cancel:
        fenced = consumer.cancel(binding["id"], pending["run_id"])
        assert fenced["state"] == "unknown"
        assert fenced["cancellation_requested"]
        assert consumer.resume(binding["id"], pending["run_id"])["state"] == "unknown"
    monkeypatch.setattr(_DemoComponents, "_initialize", original_initialize)
    authorization_id = pending["works"][-1]["execution_arguments"]["authorization_id"]
    with consumer.gate.store.operation_transaction() as db:
        grant_id = db.execute(
            "SELECT lease_id FROM governance_leases WHERE proposal_hash=?",
            (authorization_id,),
        ).fetchone()[0]
    consumer.gate.revoke_operation_authority(
        authorization_id, _build_context(), grant_id=grant_id
    )
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    recovered = (restarted.reconcile if cancel else restarted.resume)(
        binding["id"], pending["run_id"]
    )
    assert recovered["run_id"] == pending["run_id"]
    assert recovered["state"] == ("cancelled" if cancel else "completed"), recovered
    assert recovered["works"][-1]["state"] == "COMMITTED"
    assert recovered["works"][-1]["effect_verification"]["verdict"] == "MATCH"
    assert recovered["effect_counts"][work_id] == 1
    with consumer.gate.store.operation_transaction() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM governance_lease_consumption WHERE lease_id=?",
                (grant_id,),
            ).fetchone()[0]
            == 1
        )


def _independent_observation_phase_diagnostic(consumer, result):
    """Expose failure phases without dumping device output or signed payloads."""
    from nous_runtime.core.redaction import redact_sensitive_text
    from nous_runtime.node_runtime.distributed_work import DistributedWorkStore

    diagnostic = {
        "run_state": result["state"],
        "run_error": redact_sensitive_text(str(result.get("error") or ""))[:2000],
        "step_states": result["step_states"],
        "independent_observations": [
            {
                "work_id": work.work_id,
                "state": work.state.value,
                "has_result_receipt": bool(
                    work.result_summary.get("remote_execution_receipt")
                ),
            }
            for work in DistributedWorkStore(consumer.controller_state).list()
            if work.work_id.startswith("observe_")
        ],
    }
    journal_path = (
        consumer.root / ".nous" / "automation-simulation" / "node" / "workloads.json"
    )
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        diagnostic["independent_node_journals"] = [
            {
                "work_id": work_id,
                "state": entry.get("state"),
                "receipt_result": (entry.get("receipt") or {}).get("result"),
            }
            for work_id, entry in journal.items()
            if work_id.startswith("observe_")
        ]
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        diagnostic["journal_read_error"] = type(exc).__name__
    return json.dumps(diagnostic, sort_keys=True)


@pytest.mark.parametrize("verdict", ["UNKNOWN", "MISMATCH"])
def test_negative_independent_observation_never_commits_the_original_effect(
    consumer, monkeypatch, verdict
):
    from nous_runtime.reality.provider import SimulatedDeviceProvider

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    original_read = SimulatedDeviceProvider.read_state

    def contrary_read(self, device, **kwargs):
        observation = original_read(self, device, **kwargs)
        if kwargs.get("acquisition_id", "").startswith("observe_"):
            if verdict == "UNKNOWN":
                observation.metadata["stale"] = True
            else:
                observation.data["state"]["firmware_version"] = "3.0.0"
        return observation

    monkeypatch.setattr(SimulatedDeviceProvider, "read_state", contrary_read)
    result = consumer.resume(binding["id"], pending["run_id"])
    assert result["state"] != "completed"
    work_id = pending["outputs"]["mutate"]["work_id"]
    assert result["effect_counts"][work_id] == 1
    assert result["works"][-1]["state"] == "VERIFIED"
    assert "verdict" in result["works"][-1]["effect_verification"], (
        _independent_observation_phase_diagnostic(consumer, result)
    )
    assert result["works"][-1]["effect_verification"]["verdict"] == verdict
    assert result["reconciliation_required"] is (verdict == "UNKNOWN")
    monkeypatch.setattr(SimulatedDeviceProvider, "read_state", original_read)
    recovered = consumer.resume(binding["id"], pending["run_id"])
    assert recovered["state"] == "completed"
    assert recovered["effect_counts"][work_id] == 1


def test_live_http_management_nonce_history_and_original_approval_chain(
    consumer, human_env, monkeypatch
):
    from nous_runtime.api.server import RuntimeHTTPServer, RuntimeAPIHandler
    from nous_runtime.control_plane.human_sessions import HumanSessionAuth
    from nous_runtime.control_plane import human_sessions, operations
    from nous_runtime.control_plane.operations import OperationsPlane
    from nous_runtime.governance.permission import PermissionEngine, PermissionRule

    _, fixture_auth, client, _ = human_env
    permissions = PermissionEngine(
        (
            PermissionRule("oidc:*:alice", "governance.approve", "*"),
            PermissionRule("oidc:*:alice", "control.*", "*"),
        )
    )
    auth = HumanSessionAuth(
        consumer.gate.store, fixture_auth.provider, permissions=permissions
    )
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(consumer.root))
    monkeypatch.setenv("NOUS_API_TOKEN", FAKE_SERVICE_TOKEN)
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", consumer.gate)
    monkeypatch.setattr(human_sessions, "_configured_auth", auth)
    monkeypatch.setattr(
        operations,
        "_operations",
        OperationsPlane(
            consumer.root,
            gate=consumer.gate,
            controller_state=consumer.controller_state,
            device_state=consumer.root / ".nous" / "automation-simulation" / "reality",
        ),
    )
    issued, context = login(auth, client)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, *, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(
            f"http://127.0.0.1:{server.server_port}" + path,
            data=data,
            method=method,
            headers=headers or {},
        )
        try:
            response = urlopen(req, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            return json.load(response)

    def human_request(method, path, body=None):
        headers = {
            "Cookie": "apeir_human=" + issued.session_cookie,
            "Content-Type": "application/json",
        }
        if method == "POST":
            headers["X-Control-Nonce"] = auth.nonce(context, method, path, body)[
                "nonce"
            ]
        return request(method, path, body, headers=headers), headers

    try:
        add_path = "/api/v1/automations/add"
        service_headers = {
            "Authorization": "Bearer " + FAKE_SERVICE_TOKEN,
            "Content-Type": "application/json",
        }

        # Content never determines whether an HTTP caller must be human.
        # Exercise empty, legacy-only and mixed stores with the same credential.
        def service_denied(method, path, body=None):
            result = request(method, path, body, headers=service_headers)
            assert not result["ok"], result
            assert result["error"]["code"] == "NOUS_FORBIDDEN", result

        service_denied("GET", "/api/v1/automations")
        legacy_body = {"name": "Legacy human configuration"}
        legacy, legacy_headers = human_request("POST", add_path, legacy_body)
        assert legacy["ok"], legacy
        assert legacy["data"]["qualification"] == "UNQUALIFIED"
        assert (
            request("POST", add_path, legacy_body, headers=legacy_headers)["error"][
                "code"
            ]
            == "NOUS_CONTROL_REPLAY"
        )
        service_denied("GET", "/api/v1/automations")
        service_denied("POST", add_path, {"name": "Legacy HTTP configuration"})
        service_denied(
            "POST",
            "/api/v1/automations/action",
            {"action": "disable", "automation_id": legacy["data"]["id"]},
        )
        legacy_disabled, _ = human_request(
            "POST",
            "/api/v1/automations/action",
            {"action": "disable", "automation_id": legacy["data"]["id"]},
        )
        assert legacy_disabled["ok"], legacy_disabled
        assert legacy_disabled["data"]["enabled"] is False
        assert legacy_disabled["data"]["qualification"] == "UNQUALIFIED"
        body = {
            "adapter": "simulated-reality",
            "name": "Authenticated HTTP simulation",
            "trigger": "manual",
        }
        service = request(
            "POST",
            add_path,
            body,
            headers={
                "Authorization": "Bearer " + FAKE_SERVICE_TOKEN,
                "Content-Type": "application/json",
            },
        )
        assert not service["ok"]
        assert service["error"]["code"] == "NOUS_FORBIDDEN"
        created, add_headers = human_request("POST", add_path, body)
        assert created["ok"], created
        assert (
            request("POST", add_path, body, headers=add_headers)["error"]["code"]
            == "NOUS_CONTROL_REPLAY"
        )
        automation_id = created["data"]["id"]
        service_denied("GET", "/api/v1/automations")
        listing, _ = human_request("GET", "/api/v1/automations")
        assert listing["ok"], listing
        assert listing["data"]["total"] == 2
        assert any(
            item["qualification"] == "UNQUALIFIED"
            for item in listing["data"]["automations"]
        )
        pending, _ = human_request(
            "POST",
            "/api/v1/automations/action",
            {
                "action": "trigger",
                "automation_id": automation_id,
                "trigger_key": "http-original",
            },
        )
        assert pending["ok"], pending
        assert pending["data"]["state"] == "waiting_approval"
        approval, _ = human_request(
            "POST",
            "/api/v1/control/operations/actions",
            {
                "kind": "approvals",
                "action": "approve_once",
                "target_id": pending["data"]["outputs"]["mutate"][
                    "approval_request_id"
                ],
            },
        )
        assert approval["ok"], approval
        from nous_runtime.reality.preview import _DemoComponents

        original_start = _DemoComponents.start

        async def remove_management_after_start(self):
            await original_start(self)
            auth.permissions = PermissionEngine(
                (
                    PermissionRule("oidc:*:alice", "governance.approve", "*"),
                    PermissionRule("oidc:*:alice", "control.*", "*"),
                    PermissionRule(
                        "oidc:*:alice",
                        "control.automation.manage",
                        consumer.resource_id,
                        effect="deny",
                    ),
                )
            )

        with monkeypatch.context() as changed_boundary:
            changed_boundary.setattr(
                _DemoComponents, "start", remove_management_after_start
            )
            denied_resume, _ = human_request(
                "POST",
                "/api/v1/automations/action",
                {
                    "action": "resume",
                    "automation_id": automation_id,
                    "run_id": pending["data"]["run_id"],
                },
            )
            assert denied_resume["error"]["code"] == "NOUS_FORBIDDEN"
            unchanged = consumer.history(automation_id)["history"][0]
            work_id = pending["data"]["outputs"]["mutate"]["work_id"]
            assert unchanged["outputs"]["mutate"]["work_id"] == work_id
            assert unchanged["works"][-1]["state"] == "CREATED"
            assert unchanged["effect_counts"][work_id] == 0
        auth.permissions = permissions
        completed, _ = human_request(
            "POST",
            "/api/v1/automations/action",
            {
                "action": "resume",
                "automation_id": automation_id,
                "run_id": pending["data"]["run_id"],
            },
        )
        assert completed["ok"], completed
        verification = completed["data"]["outputs"]["mutate"].get("effect_verification")
        # Preserve the strict MATCH requirement and expose the original state,
        # error and evidence on failure instead of losing them to KeyError (#82).
        assert (
            isinstance(verification, dict) and verification.get("verdict") == "MATCH"
        ), completed
        assert completed["data"]["outputs"]["mutate"]["work_id"] == work_id, completed
        assert completed["data"]["effect_counts"][work_id] == 1, completed
        path = f"/api/v1/automations/{automation_id}/history"
        history, _ = human_request("GET", path)
        assert history["ok"], history
        assert (
            history["data"]["history"][0]["run"]["run_id"] == pending["data"]["run_id"]
        )
        permissions.add(
            PermissionRule(
                "oidc:*:alice",
                "control.automation.read",
                consumer.resource_id,
                effect="deny",
            )
        )
        denied, _ = human_request("GET", path)
        assert denied["error"]["code"] == "NOUS_FORBIDDEN"
        denied_listing, _ = human_request("GET", "/api/v1/automations")
        assert denied_listing["error"]["code"] == "NOUS_FORBIDDEN"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def automation_http(consumer, human_env, monkeypatch):
    """Use the public HTTP route with real fake-OIDC sessions and bound nonces."""
    from nous_runtime.api.server import RuntimeHTTPServer, RuntimeAPIHandler
    from nous_runtime.control_plane import human_sessions
    from nous_runtime.control_plane.human_sessions import HumanSessionAuth
    from nous_runtime.governance.permission import PermissionEngine, PermissionRule

    _, fixture_auth, client, _ = human_env
    auth = HumanSessionAuth(
        consumer.gate.store,
        fixture_auth.provider,
        permissions=PermissionEngine(
            (
                PermissionRule("oidc:*:alice", "governance.approve", "*"),
                PermissionRule("oidc:*:alice", "control.*", "*"),
            )
        ),
    )
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(consumer.root))
    monkeypatch.setenv("NOUS_API_TOKEN", FAKE_SERVICE_TOKEN)
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", consumer.gate)
    monkeypatch.setattr(human_sessions, "_configured_auth", auth)
    issued, context = login(auth, client)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(body, nonce, path="/api/v1/automations/action"):
        req = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Cookie": "apeir_human=" + issued.session_cookie,
                "Content-Type": "application/json",
                "X-Control-Nonce": nonce,
            },
        )
        try:
            response = urlopen(req, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            return json.load(response)

    try:
        yield auth, context, request
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("revocation", ["session", "permission", "none"])
def test_http_toggle_revalidates_after_workflow_writer_admission(
    consumer, automation_http, monkeypatch, action, revocation
):
    from nous_runtime.governance.permission import PermissionRule

    auth, context, request = automation_http
    binding = consumer.add_simulation(name="Original toggle configuration")
    before_enabled = action == "disable"
    consumer.store.set_automation_enabled(binding["id"], before_enabled)
    original = consumer.store.get_automation(binding["id"])
    body = {"action": action, "automation_id": binding["id"]}
    nonce = auth.nonce(context, "POST", "/api/v1/automations/action", body)["nonce"]
    writer_attempt = Event()
    blockers = []
    scoped = local()
    connect = WorkflowStore._connect
    toggle = WorkflowStore.set_automation_enabled

    def traced_connect(self):
        connection = connect(self)
        if getattr(scoped, "toggle", False):
            connection.set_trace_callback(
                lambda sql: writer_attempt.set() if sql == "BEGIN IMMEDIATE" else None
            )
        return connection

    def held_toggle(self, *args, **kwargs):
        # Install actual writer contention after the public route's admissions.
        blocker = sqlite3.connect(self.path, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")
        blockers.append(blocker)
        scoped.toggle = True
        try:
            return toggle(self, *args, **kwargs)
        finally:
            scoped.toggle = False

    monkeypatch.setattr(WorkflowStore, "_connect", traced_connect)
    monkeypatch.setattr(WorkflowStore, "set_automation_enabled", held_toggle)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(request, body, nonce)
        try:
            assert writer_attempt.wait(timeout=10)
            assert not future.done()
            assert consumer.store.get_automation(binding["id"]) == original
            with consumer.gate.store.operation_transaction() as db:
                rows = db.execute(
                    "SELECT consumed FROM governance_human_nonces"
                ).fetchall()
                assert len(rows) == 1 and rows[0][0] == 1
            if revocation == "session":
                auth.logout(context)
            elif revocation == "permission":
                auth.permissions.add(
                    PermissionRule(
                        "oidc:*:alice",
                        "control.automation.manage",
                        consumer.resource_id,
                        effect="deny",
                    )
                )
            if revocation != "none":
                with pytest.raises(PermissionError):
                    consumer.admit_management(context, audit=False)
            else:
                consumer.admit_management(context, audit=False)
            assert not future.done()
            assert consumer.store.get_automation(binding["id"]) == original
        finally:
            for blocker in blockers:
                blocker.rollback()
                blocker.close()
        result = future.result(timeout=15)
    if revocation == "none":
        assert result["ok"], result
        expected = {**original, "enabled": not before_enabled}
        assert result["data"] == expected
    else:
        assert result["error"]["code"] == "NOUS_FORBIDDEN", result
        expected = original
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    assert restarted.store.get_automation(binding["id"]) == expected
    assert restarted.store.automation_history(binding["id"]) == []
    with consumer.gate.store.operation_transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM governance_leases").fetchone()[0] == 0
    replay = request(body, nonce)
    assert replay["error"]["code"] == (
        "NOUS_UNAUTHENTICATED" if revocation == "session" else "NOUS_CONTROL_REPLAY"
    )


@pytest.mark.parametrize("definition", ["changed", "removed"])
def test_toggle_rejects_changed_or_removed_original_definition(consumer, definition):
    binding = consumer.add_simulation(name="Original immutable definition")
    original = consumer.store.get_automation(binding["id"])
    with consumer.store._db() as db:
        if definition == "removed":
            db.execute(
                "DELETE FROM workflow_definitions WHERE workflow_id=? AND version=?",
                (binding["workflow_id"], binding["version"]),
            )
        else:
            row = db.execute(
                "SELECT definition_json FROM workflow_definitions WHERE workflow_id=? AND version=?",
                (binding["workflow_id"], binding["version"]),
            ).fetchone()
            changed = json.loads(row[0])
            changed["steps"][0]["params"]["changed"] = True
            db.execute(
                "UPDATE workflow_definitions SET definition_json=? WHERE workflow_id=? AND version=?",
                (json.dumps(changed), binding["workflow_id"], binding["version"]),
            )
    with pytest.raises(WorkflowBindingError):
        consumer.store.set_automation_enabled(
            binding["id"],
            False,
            before_publish=lambda: pytest.fail("invalid binding cannot be published"),
        )
    assert WorkflowStore(consumer.root).get_automation(binding["id"]) == original


def test_trusted_local_toggle_remains_configuration_only(consumer):
    binding = consumer.add_simulation(name="Trusted local configuration")
    for enabled in (False, True):
        expected = {**binding, "enabled": enabled}
        assert consumer.store.set_automation_enabled(binding["id"], enabled) == expected
        assert WorkflowStore(consumer.root).get_automation(binding["id"]) == expected
    with pytest.raises(KeyError):
        consumer.store.set_automation_enabled(
            "missing-automation",
            True,
            before_publish=lambda: pytest.fail("missing binding cannot be published"),
        )
    assert consumer.store.automation_history(binding["id"]) == []


def test_cancellation_at_node_admission_blocks_effect_and_survives_restart(
    consumer, monkeypatch
):
    from nous_runtime.reality.execution import SimulatedDeviceOperationHandler

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    entered = Event()
    release = Event()
    original = SimulatedDeviceOperationHandler.execute_bound

    def hold_at_admission(self, *args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        SimulatedDeviceOperationHandler, "execute_bound", hold_at_admission
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(consumer.resume, binding["id"], pending["run_id"])
        assert entered.wait(timeout=10)
        try:
            interrupted = consumer.cancel(binding["id"], pending["run_id"])
            assert interrupted["cancellation_requested"]
            assert interrupted["reconciliation_required"]
        finally:
            release.set()
        result = future.result(timeout=15)
    work_id = pending["outputs"]["mutate"]["work_id"]
    assert result["effect_counts"][work_id] == 0
    assert result["works"][-1]["state"] == "FAILED"
    assert result["cancellation_requested"]
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    assert (
        restarted.resume(binding["id"], pending["run_id"])["effect_counts"][work_id]
        == 0
    )


def test_history_and_duplicate_cannot_claim_success_after_artifact_tampering(consumer):
    from nous_runtime.core.errors import ArtifactError

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    ref = completed["works"][-1]["evidence_refs"][-1]
    cas = ContentAddressedArtifactStore(consumer.controller_state / "artifacts")
    cas.resolve("sha256:" + ref.removeprefix("artifact://sha256/")).write_bytes(
        b"tampered evidence"
    )
    with pytest.raises(ArtifactError, match="integrity"):
        consumer.history(binding["id"])
    with pytest.raises(ArtifactError, match="integrity"):
        consumer.trigger(binding["id"], "original")


def test_cli_is_explicit_simulation_and_consumes_original_workflow(
    consumer, monkeypatch
):
    from typer.testing import CliRunner
    from nous_runtime.cli.main import app

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(consumer.root))
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", consumer.gate)
    runner = CliRunner()
    assert (
        runner.invoke(
            app, ["automation", "add", "Explicit simulation required"]
        ).exit_code
        == 2
    )
    created = runner.invoke(
        app, ["automation", "add", "Real CLI simulation", "--simulation"]
    )
    assert created.exit_code == 0, created.output
    automation_id = json.loads(created.output)["id"]
    pending = runner.invoke(
        app,
        [
            "automation",
            "trigger",
            automation_id,
            "--trigger-key",
            "cli-original",
            "--simulation",
        ],
    )
    assert pending.exit_code == 0, pending.output
    original = json.loads(pending.output)
    assert original["state"] == "waiting_approval"
    approval = runner.invoke(
        app,
        ["approval", "approve", original["outputs"]["mutate"]["approval_request_id"]],
    )
    assert approval.exit_code == 0, approval.output
    completed = runner.invoke(
        app, ["automation", "resume", automation_id, original["run_id"], "--simulation"]
    )
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.output)["outputs"]["mutate"]["state"] == "COMMITTED"


def test_restart_between_atomic_trigger_claim_and_handler_recovers_the_same_pending_run(
    consumer, monkeypatch
):
    binding = consumer.add_simulation(name="Claim then restart")

    def lost_consumer(*args, **kwargs):
        raise OSError("consumer stopped after original trigger claim")

    monkeypatch.setattr(consumer, "_consume", lost_consumer)
    with pytest.raises(OSError):
        consumer.trigger(binding["id"], "original")
    original = consumer.store.automation_history(binding["id"])[0]["run"]
    assert original["state"] == "pending"
    assert original["outputs"] == {}
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    resumed = restarted.resume(binding["id"], original["run_id"])
    assert resumed["run_id"] == original["run_id"]
    assert resumed["state"] == "waiting_approval"
    assert (
        consumer.store.automation_history(binding["id"])[0]["run"]["run_id"]
        == original["run_id"]
    )


@pytest.mark.parametrize(
    "journal",
    [
        "missing",
        "missing-file",
        "started",
        "cancelled",
        "controller-state",
        "invalid-json",
        "invalid-root",
        "invalid-entry",
        "journal-key",
        "workload-id",
        "capability",
        "binding",
        "request-digest",
        "missing-receipt",
        "receipt-operation",
        "receipt-node",
        "receipt-input",
        "receipt-result",
        "delivery-semantics",
        "effect-digest",
        "output",
    ],
)
def test_unresolved_original_work_with_invalid_node_journal_never_opens_dispatch(
    consumer, monkeypatch, journal
):
    from nous_runtime.reality.preview import _DemoComponents, STABLE_ID
    from nous_runtime.reality import SimulationFault

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    original_initialize = _DemoComponents._initialize

    def inject_response_loss(self, *args, **kwargs):
        original_initialize(self, *args, **kwargs)
        self.response_loss = True
        self.provider.inject_fault(STABLE_ID, SimulationFault.EFFECT_THEN_RESPONSE_LOST)

    monkeypatch.setattr(_DemoComponents, "_initialize", inject_response_loss)
    uncertain = consumer.resume(binding["id"], pending["run_id"])
    work_id = pending["outputs"]["mutate"]["work_id"]
    assert uncertain["effect_counts"][work_id] == 1
    with consumer.gate.store.operation_transaction() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM governance_lease_consumption").fetchone()[
                0
            ]
            == 1
        )
    monkeypatch.setattr(_DemoComponents, "_initialize", original_initialize)
    path = consumer.root / ".nous" / "automation-simulation" / "node" / "workloads.json"
    original_records = json.loads(path.read_text(encoding="utf-8"))
    records = dict(original_records)
    if journal == "missing":
        records.pop(work_id)
    elif journal == "started":
        records[work_id] = {**records[work_id], "state": "EXECUTING"}
        records[work_id].pop("receipt", None)
    elif journal == "cancelled":
        records[work_id] = {
            "workload_id": work_id,
            "capability": "",
            "state": "CANCELLED",
            "stop_result": "CANCELLED_BEFORE_START",
            "started_at": records[work_id]["started_at"],
            "finished_at": records[work_id]["finished_at"],
        }
    elif journal == "controller-state":
        records[work_id]["state"] = "SUCCEEDED"
    elif journal == "invalid-entry":
        records[work_id] = "damaged terminal record"
    elif journal == "journal-key":
        records["another-work"] = records.pop(work_id)
    elif journal == "workload-id":
        records[work_id]["workload_id"] = "another-work"
    elif journal == "capability":
        records[work_id]["capability"] = "device.state.read"
    elif journal == "binding":
        records[work_id]["binding"]["target_ref"] = "device://another-device"
    elif journal == "request-digest":
        records[work_id]["request_digest"] = "0" * 64
    elif journal == "missing-receipt":
        records[work_id].pop("receipt")
    elif journal == "receipt-operation":
        records[work_id]["receipt"]["operation_id"] = "another-work"
    elif journal == "receipt-node":
        records[work_id]["receipt"]["node_id"] = "another-node"
    elif journal == "receipt-input":
        records[work_id]["receipt"]["input_digest"] = "0" * 64
    elif journal == "receipt-result":
        records[work_id]["receipt"]["result"] = "FAILED"
    elif journal == "delivery-semantics":
        records[work_id]["delivery_semantics"] = "idempotent"
    elif journal == "effect-digest":
        records[work_id]["receipt"]["effect_digest"] = "0" * 64
    elif journal == "output":
        records[work_id]["output"]["unexpected"] = "changed result"
    if journal == "missing-file":
        path.unlink()
    elif journal == "invalid-json":
        path.write_text("{incomplete", encoding="utf-8")
    elif journal == "invalid-root":
        path.write_text("[]", encoding="utf-8")
    else:
        path.write_text(json.dumps(records), encoding="utf-8")

    def no_transport(self):
        raise AssertionError(
            "Uncertain original journal must never open the dispatch transport"
        )

    monkeypatch.setattr(_DemoComponents, "start", no_transport)
    for action in (consumer.resume, consumer.reconcile):
        restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
        result = getattr(restarted, action.__name__)(binding["id"], pending["run_id"])
        assert result["state"] == "unknown"
        assert result["reconciliation_required"]
        assert result["effect_counts"][work_id] == 1
    assert (
        consumer.store.automation_history(binding["id"])[0]["run"]["run_id"]
        == pending["run_id"]
    )
    with consumer.gate.store.operation_transaction() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM governance_lease_consumption").fetchone()[
                0
            ]
            == 1
        )
    if journal == "missing":
        another = consumer.add_simulation(
            name="Cannot reopen another original delivery"
        )
        blocked = consumer.trigger(another["id"], "different-original")
        assert blocked["state"] == "unknown"
        assert blocked["works"] == []
        assert (
            consumer.history(binding["id"])["history"][0]["effect_counts"][work_id] == 1
        )


def test_explicit_simulation_add_binds_a_registered_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", None)
    result = handle_automations_add(
        {
            "name": "Governed simulated firmware",
            "adapter": "simulated-reality",
            "trigger": "manual",
        },
        authorization_context=_build_context(),
    )
    assert result["ok"], result
    assert result["data"].get("workflow_id"), (
        "Automation has no original Workflow consumer binding"
    )
    assert result["data"]["simulated"] is True


@pytest.mark.parametrize(
    "changed",
    [
        "assignment-work",
        "assignment-node",
        "assignment-input",
        "assignment-policy",
        "dispatch-work",
        "dispatch-assignment",
        "dispatch-node",
        "dispatch-input",
        "dispatch-delivery",
        "dispatch-request",
        "operation-work",
        "operation-id",
        "operation-run",
        "operation-node",
        "operation-capability",
        "operation-resource",
        "operation-effect",
        "operation-input",
    ],
)
def test_terminal_evidence_requires_exact_original_work_and_authorization_provenance(
    consumer, monkeypatch, changed
):
    from nous_runtime.reality.preview import create_automation_simulation_components

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    original_request_reader = consumer.gate.get_operation_request
    work = deepcopy(completed["works"][-1])
    components = create_automation_simulation_components(
        consumer.root, governance=consumer.gate
    )
    try:
        assert consumer._terminal_journals_match(components, [work])
        group, field = changed.split("-", 1)
        if group == "assignment":
            field = {
                "work": "work_id",
                "node": "node_id",
                "input": "input_artifacts",
                "policy": "execution_policy",
            }[field]
            work["assignment"][field] = [] if field == "input_artifacts" else "changed"
        elif group == "dispatch":
            field = {
                "work": "work_id",
                "assignment": "assignment_id",
                "node": "node_id",
                "input": "input_artifacts",
                "delivery": "delivery",
                "request": "provider_request_digest",
            }[field]
            work["dispatch_record"][field] = (
                [] if field == "input_artifacts" else "changed"
            )
        else:
            field = {
                "work": "work_id",
                "id": "operation_id",
                "run": "workflow_run_id",
                "node": "node_id",
                "capability": "capability_id",
                "resource": "resource_id",
                "effect": "expected_effect",
                "input": "input_artifacts",
            }[field]
            original = consumer.gate.get_operation_request(
                work["execution_arguments"]["authorization_id"]
            )
            altered = replace(
                original,
                **{
                    field: ()
                    if field == "input_artifacts"
                    else {"changed": True}
                    if field == "expected_effect"
                    else "changed"
                },
            )
            monkeypatch.setattr(
                consumer.gate, "get_operation_request", lambda _: altered
            )
        assert not consumer._terminal_journals_match(components, [work])
        assert components.server._server is None
        # The projection now checks Governance evidence too. Restore the real
        # reader after the deliberately changed preflight request was rejected.
        monkeypatch.setattr(
            consumer.gate, "get_operation_request", original_request_reader
        )
        assert (
            consumer._projection(binding["id"], pending["run_id"])["effect_counts"][
                work["work_id"]
            ]
            == 1
        )
    finally:
        asyncio.run(components.close())


@pytest.mark.parametrize(
    "changed",
    [
        "expected-effect",
        "capability",
        "device",
        "plan",
        "step",
        "operation",
        "inputs",
        "receipt",
        "verification-device",
        "verification-observations",
        "verification-receipt",
        "verification-verdict",
        "verification-proof",
        "observation-proof",
    ],
)
def test_committed_history_rejects_changed_original_semantic_evidence(
    consumer, changed
):
    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    work_id = completed["outputs"]["mutate"]["work_id"]
    path = consumer.controller_state / "distributed-works.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    work = document["works"][work_id]
    prefix = "distributed Workflow Work timed out: observe_"
    mutation_result_timeout = (
        completed["state"] == "failed"
        and completed.get("error", "")
        == f"distributed Workflow Work timed out: {work_id}"
    )
    observation_timeout = completed["state"] == "failed" and completed.get(
        "error", ""
    ).startswith(prefix)
    if mutation_result_timeout:
        from nous_runtime.reality.preview import create_automation_simulation_components

        assert work["state"] == "RUNNING"
        assert not work["result_summary"].get("remote_execution_receipt")
        assert not work["effect_verification"]
        assert completed["effect_counts"][work_id] == 1
        assert completed["reconciliation_required"]
        components = create_automation_simulation_components(
            consumer.root, governance=consumer.gate
        )
        try:
            # Result delivery is distinct from Node completion. Require the
            # original signed terminal journal before opening recovery transport.
            assert consumer._terminal_journals_match(components, [work])
            assert components.server._server is None
        finally:
            asyncio.run(components.close())
    elif observation_timeout:
        from nous_runtime.node_runtime.distributed_work import DistributedWorkStore

        acquisition_id = completed["error"].removeprefix(
            "distributed Workflow Work timed out: "
        )
        read = DistributedWorkStore(consumer.controller_state).get(acquisition_id)
        assert read is not None
        assert read.execution_capability == "device.state.read"
        assert read.target_resource_id == work["target_resource_id"]
        assert read.assigned_node == work["assigned_node"]
        assert read.provenance["workflow_run_id"] == pending["run_id"]
        assert read.execution_arguments["acquisition_id"] == acquisition_id
        assert read.input_artifacts == tuple(work["input_artifacts"])
        assert not read.execution_policy.require_effect_verification
        assert work["state"] == "VERIFIED"
        assert not work["effect_verification"]
        assert completed["effect_counts"][work_id] == 1
        assert completed["reconciliation_required"]
    if mutation_result_timeout or observation_timeout:
        from nous_runtime.reality.provider import SimulatedDeviceProvider

        # One explicit recovery of the original effect, not another mutation or
        # a retry-until-success fixture. Unknown/mismatched evidence still fails.
        with pytest.MonkeyPatch.context() as recovery:
            recovery.setattr(
                SimulatedDeviceProvider,
                "apply_operation",
                lambda *_args, **_kwargs: pytest.fail(
                    "tamper precondition recovery cannot repeat the original effect"
                ),
            )
            consumer.reconcile(binding["id"], pending["run_id"])
            completed = consumer.resume(binding["id"], pending["run_id"])
        assert completed["run_id"] == pending["run_id"]
        assert completed["outputs"]["mutate"]["work_id"] == work_id
        document = json.loads(path.read_text(encoding="utf-8"))
        work = document["works"][work_id]
    before_tamper = (
        f"workflow={completed['state']} work={work['state']} "
        f"verdict={work['effect_verification'].get('verdict', 'missing')} "
        f"read_timeout={str(completed.get('error', '')).startswith(prefix)} "
        f"reconcile={completed['reconciliation_required']} "
        f"effects={completed['effect_counts'][work_id]}"
    )
    assert completed["state"] == "completed", before_tamper
    assert work["state"] == "COMMITTED", before_tamper
    if changed == "expected-effect":
        work["expected_effect"] = {"firmware_version": "9.9.9"}
    elif changed == "capability":
        work["execution_capability"] = "device.state.read"
    elif changed == "device":
        work["target_resource_id"] = "another-device"
    elif changed in {"plan", "step"}:
        work["provenance"]["plan_id" if changed == "plan" else "workflow_step_id"] = (
            "other"
        )
    elif changed == "operation":
        work["execution_arguments"]["operation"]["operation_id"] = "other"
    elif changed == "inputs":
        work["input_artifacts"] = []
    elif changed == "receipt":
        work["result_summary"]["remote_execution_receipt"]["node_id"] = "other"
    elif changed.startswith("verification-"):
        field = changed.removeprefix("verification-")
        if field == "proof":
            cas = ContentAddressedArtifactStore(consumer.controller_state / "artifacts")
            work["evidence_refs"] = [
                ref
                for ref in work["evidence_refs"]
                if cas.get(
                    "sha256:" + ref.removeprefix("artifact://sha256/")
                ).media_type
                != "application/vnd.apeir.effect-verification+json"
            ]
        else:
            key = {
                "device": "device_id",
                "observations": "observation_ids",
                "receipt": "receipt_digest",
                "verdict": "verdict",
            }[field]
            work["effect_verification"][key] = (
                ["other"]
                if key == "observation_ids"
                else "UNKNOWN"
                if key == "verdict"
                else "other"
            )
    else:
        cas = ContentAddressedArtifactStore(consumer.controller_state / "artifacts")
        work["evidence_refs"] = [
            ref
            for ref in work["evidence_refs"]
            if cas.get("sha256:" + ref.removeprefix("artifact://sha256/")).media_type
            != "application/vnd.apeir.observation+json"
        ]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WorkflowBindingError):
        AutomationConsumer(consumer.root, gate=consumer.gate).history(binding["id"])
    assert completed["effect_counts"][work_id] == 1


def test_committed_history_after_grant_revocation_reads_original_evidence_only(
    consumer, monkeypatch
):
    from nous_runtime.reality.preview import _DemoComponents

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    work_id = completed["outputs"]["mutate"]["work_id"]
    authorization_id = completed["works"][-1]["execution_arguments"]["authorization_id"]
    with consumer.gate.store.operation_transaction() as db:
        grant_id = db.execute(
            "SELECT lease_id FROM governance_leases WHERE proposal_hash=?",
            (authorization_id,),
        ).fetchone()[0]
    consumer.gate.revoke_operation_authority(
        authorization_id, _build_context(), grant_id=grant_id
    )
    monkeypatch.setattr(
        _DemoComponents, "start", lambda _: pytest.fail("history cannot open transport")
    )
    monkeypatch.setattr(
        consumer.gate,
        "evaluate_operation",
        lambda *_: pytest.fail("history is not new execution admission"),
    )
    history = AutomationConsumer(consumer.root, gate=consumer.gate).history(
        binding["id"]
    )
    result = history["history"][0]
    assert result["state"] == "completed"
    assert result["works"][-1]["state"] == "COMMITTED"
    assert result["works"][-1]["effect_verification"]["verdict"] == "MATCH"
    assert result["effect_counts"][work_id] == 1


def test_committed_history_recovers_original_read_loss_before_tamper_check(
    consumer, monkeypatch
):
    from nous_runtime.node_runtime.relay import NodeRelayClient

    dropped = []
    send = NodeRelayClient._send

    async def lose_first_observation(self, websocket, message_type, payload, **kwargs):
        if (
            message_type == "WORKLOAD_STATUS"
            and str(payload.get("workload_id", "")).startswith("observe_")
            and not dropped
        ):
            dropped.append(payload["output"]["observation_id"])
            return
        return await send(self, websocket, message_type, payload, **kwargs)

    monkeypatch.setattr(NodeRelayClient, "_send", lose_first_observation)
    test_committed_history_rejects_changed_original_semantic_evidence(
        consumer, "receipt"
    )
    assert len(dropped) == 1


def test_committed_history_recovers_original_mutation_result_loss_before_tamper_check(
    consumer, monkeypatch
):
    from nous_runtime.node_runtime.relay import NodeRelayClient

    dropped = []
    send = NodeRelayClient._send

    async def lose_first_mutation(self, websocket, message_type, payload, **kwargs):
        if (
            message_type == "WORKLOAD_STATUS"
            and (payload.get("output") or {}).get("effect_applied") is True
            and not dropped
        ):
            dropped.append(payload["workload_id"])
            return
        return await send(self, websocket, message_type, payload, **kwargs)

    monkeypatch.setattr(NodeRelayClient, "_send", lose_first_mutation)
    test_committed_history_rejects_changed_original_semantic_evidence(
        consumer, "device"
    )
    assert len(dropped) == 1


@pytest.mark.parametrize("proof", ["verification", "observation"])
def test_history_rejects_rehashed_semantic_proof_with_valid_cas_bytes(consumer, proof):
    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    work_id = completed["outputs"]["mutate"]["work_id"]
    path = consumer.controller_state / "distributed-works.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    work = document["works"][work_id]
    cas = ContentAddressedArtifactStore(consumer.controller_state / "artifacts")
    media_type = (
        "application/vnd.apeir.effect-verification+json"
        if proof == "verification"
        else "application/vnd.apeir.observation+json"
    )
    ref = next(
        ref
        for ref in work["evidence_refs"]
        if cas.get("sha256:" + ref.removeprefix("artifact://sha256/")).media_type
        == media_type
    )
    artifact = cas.get("sha256:" + ref.removeprefix("artifact://sha256/"))
    original_bytes = cas.resolve(artifact.digest, verify=True).read_bytes()
    value = json.loads(original_bytes)
    if proof == "verification":
        value["device_id"] = "other-device"
        work["effect_verification"] = value
    else:
        value["data"]["state"]["firmware_version"] = "9.9.9"
    stored = cas.store_bytes(
        json.dumps(value).encode(),
        artifact_type=artifact.artifact_type,
        name=artifact.name,
        media_type=artifact.media_type,
        produced_by=artifact.produced_by,
        depends_on=artifact.depends_on,
        derived_from=artifact.derived_from,
        metadata=artifact.metadata,
    )
    digest = stored["artifact"]["digest"]
    assert cas.verify(digest)
    work["evidence_refs"][work["evidence_refs"].index(ref)] = (
        "artifact://sha256/" + digest.removeprefix("sha256:")
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WorkflowBindingError):
        consumer.history(binding["id"])
    assert cas.resolve(artifact.digest, verify=True).read_bytes() == original_bytes


def test_history_retains_old_signed_evidence_without_transport_clock_freshness(
    consumer, monkeypatch
):
    from nous_runtime.node_runtime import protocol

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    snapshots = {
        path: path.read_bytes() for path in consumer.controller_state.rglob("*.json")
    }

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=2)

    monkeypatch.setattr(protocol, "datetime", LaterClock)
    result = consumer.history(binding["id"])["history"][0]
    assert result["works"] == completed["works"]
    assert result["effect_counts"] == completed["effect_counts"]
    assert all(path.read_bytes() == value for path, value in snapshots.items())


@pytest.mark.parametrize(
    "changed",
    [
        "missing-output",
        "non-dict-output",
        "missing-work-id",
        "extra-output",
        "different-work-id",
        "changed-output",
        "missing-checkpoint",
        "changed-checkpoint",
        "changed-step-state",
        "uncommitted-work",
    ],
)
def test_completed_history_requires_every_original_step_output_and_checkpoint(
    consumer, monkeypatch, changed
):
    from nous_runtime.reality.preview import _DemoComponents

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    work_id = completed["outputs"]["mutate"]["work_id"]
    with consumer.store._db() as db:
        row = db.execute(
            "SELECT run_json FROM workflow_runs WHERE run_id=?", (pending["run_id"],)
        ).fetchone()
        run = json.loads(row[0])
        if changed == "missing-output":
            del run["outputs"]["mutate"]
        elif changed == "non-dict-output":
            run["outputs"]["mutate"] = "COMMITTED"
        elif changed == "missing-work-id":
            del run["outputs"]["mutate"]["work_id"]
        elif changed == "extra-output":
            run["outputs"]["unregistered"] = deepcopy(run["outputs"]["mutate"])
        elif changed == "different-work-id":
            run["outputs"]["mutate"]["work_id"] = run["outputs"]["inspect"]["work_id"]
        elif changed == "changed-output":
            run["outputs"]["mutate"]["effect_verification"]["verdict"] = "UNKNOWN"
        elif changed == "changed-step-state":
            run["step_states"]["mutate"] = "unknown"
        elif changed == "missing-checkpoint":
            db.execute(
                "DELETE FROM workflow_checkpoints WHERE run_id=? AND step_id='mutate'",
                (pending["run_id"],),
            )
        elif changed == "changed-checkpoint":
            row = db.execute(
                "SELECT checkpoint_json FROM workflow_checkpoints WHERE run_id=? AND step_id='mutate'",
                (pending["run_id"],),
            ).fetchone()
            checkpoint = json.loads(row[0])
            checkpoint["status"] = "unknown"
            db.execute(
                "UPDATE workflow_checkpoints SET checkpoint_json=? WHERE run_id=? AND step_id='mutate'",
                (json.dumps(checkpoint), pending["run_id"]),
            )
        db.execute(
            "UPDATE workflow_runs SET run_json=? WHERE run_id=?",
            (json.dumps(run), pending["run_id"]),
        )
    if changed == "uncommitted-work":
        path = consumer.controller_state / "distributed-works.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["works"][work_id]["state"] = "UNKNOWN"
        path.write_text(json.dumps(document), encoding="utf-8")
    snapshots = {
        path: path.read_bytes() for path in consumer.controller_state.rglob("*.json")
    }
    monkeypatch.setattr(
        _DemoComponents, "start", lambda _: pytest.fail("history cannot open transport")
    )
    monkeypatch.setattr(
        consumer.gate,
        "evaluate_operation",
        lambda *_: pytest.fail("history cannot admit execution"),
    )
    with pytest.raises(WorkflowBindingError):
        consumer.history(binding["id"])
    assert all(path.read_bytes() == value for path, value in snapshots.items())
    assert completed["effect_counts"][work_id] == 1


@pytest.mark.parametrize("phase", ["unstarted", "waiting_approval", "cancelled"])
def test_incomplete_honest_history_is_readable_without_execution(
    consumer, monkeypatch, phase
):
    from nous_runtime.reality.preview import _DemoComponents
    from nous_runtime.reality.provider import SimulatedDeviceProvider

    binding = consumer.add_simulation(name="Original partial history")
    if phase == "unstarted":
        original = consumer.store.claim_automation_run(binding["id"], "original")
        expected_state = "pending"
        run_id = original.run_id
    else:
        original = consumer.trigger(binding["id"], "original")
        run_id = original["run_id"]
        expected_state = phase
        if phase == "cancelled":
            consumer.cancel(binding["id"], run_id)
    snapshots = {
        path: path.read_bytes() for path in consumer.controller_state.rglob("*.json")
    }
    monkeypatch.setattr(
        _DemoComponents, "start", lambda _: pytest.fail("history cannot open transport")
    )
    monkeypatch.setattr(
        SimulatedDeviceProvider,
        "apply_operation",
        lambda *_args, **_kwargs: pytest.fail("history cannot mutate state"),
    )
    monkeypatch.setattr(
        SimulatedDeviceProvider,
        "read_state",
        lambda *_args, **_kwargs: pytest.fail("history cannot acquire new Observation"),
    )
    result = consumer.history(binding["id"])["history"][0]
    assert result["run_id"] == run_id
    assert result["state"] == expected_state
    assert all(count == 0 for count in result["effect_counts"].values())
    assert all(path.read_bytes() == value for path, value in snapshots.items())


def test_response_loss_reconcile_then_resume_completes_only_the_original_run(
    consumer, monkeypatch
):
    from nous_runtime.reality import SimulationFault
    from nous_runtime.reality.preview import _DemoComponents, STABLE_ID
    from nous_runtime.reality.provider import SimulatedDeviceProvider

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    initialize = _DemoComponents._initialize

    def lose_response(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        self.response_loss = True
        self.provider.inject_fault(STABLE_ID, SimulationFault.EFFECT_THEN_RESPONSE_LOST)

    monkeypatch.setattr(_DemoComponents, "_initialize", lose_response)
    uncertain = consumer.resume(binding["id"], pending["run_id"])
    work_id = pending["outputs"]["mutate"]["work_id"]
    assert uncertain["state"] == "failed"
    assert uncertain["reconciliation_required"]
    assert uncertain["effect_counts"][work_id] == 1
    monkeypatch.setattr(_DemoComponents, "_initialize", initialize)
    monkeypatch.setattr(
        SimulatedDeviceProvider,
        "apply_operation",
        lambda *_args, **_kwargs: pytest.fail(
            "recovery cannot execute the side effect again"
        ),
    )
    original_works = {work["work_id"] for work in uncertain["works"]}
    reconciled = consumer.reconcile(binding["id"], pending["run_id"])
    assert reconciled["state"] == "failed"
    assert not reconciled["reconciliation_required"]
    assert all(work["state"] == "COMMITTED" for work in reconciled["works"])
    assert reconciled["works"][-1]["effect_verification"]["verdict"] == "MATCH"
    completed = consumer.resume(binding["id"], pending["run_id"])
    assert completed["state"] == "completed"
    assert completed["run_id"] == pending["run_id"]
    assert completed["outputs"]["mutate"]["work_id"] == work_id
    assert {work["work_id"] for work in completed["works"]} == original_works
    assert completed["effect_counts"][work_id] == 1
    assert len(consumer.history(binding["id"])["history"]) == 1


@pytest.mark.parametrize("revocation", ["session", "permission", "none"])
def test_http_creation_revalidates_after_binding_writer_admission(
    consumer, automation_http, monkeypatch, revocation
):
    from nous_runtime.governance.permission import PermissionRule

    auth, context, request = automation_http
    path = "/api/v1/automations/add"
    body = {"adapter": "simulated-reality", "name": "Original governed configuration"}
    nonce = auth.nonce(context, "POST", path, body)["nonce"]
    writer_attempt = Event()
    blockers = []
    scoped = local()
    connect = WorkflowStore._connect
    put = WorkflowStore.put_automation

    def traced_connect(self):
        connection = connect(self)
        if getattr(scoped, "creation", False):
            connection.set_trace_callback(
                lambda sql: writer_attempt.set() if sql == "BEGIN IMMEDIATE" else None
            )
        return connection

    def held_publication(self, *args, **kwargs):
        blocker = sqlite3.connect(self.path, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")
        blockers.append(blocker)
        scoped.creation = True
        try:
            return put(self, *args, **kwargs)
        finally:
            scoped.creation = False

    monkeypatch.setattr(WorkflowStore, "_connect", traced_connect)
    monkeypatch.setattr(WorkflowStore, "put_automation", held_publication)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(request, body, nonce, path)
        try:
            assert writer_attempt.wait(timeout=10)
            assert not future.done()
            assert consumer.store.list_automations() == []
            if revocation == "session":
                auth.logout(context)
            elif revocation == "permission":
                auth.permissions.add(
                    PermissionRule(
                        "oidc:*:alice",
                        "control.automation.manage",
                        consumer.resource_id,
                        effect="deny",
                    )
                )
            if revocation != "none":
                with pytest.raises(PermissionError):
                    consumer.admit_management(context, audit=False)
            assert not future.done()
        finally:
            for blocker in blockers:
                blocker.rollback()
                blocker.close()
        result = future.result(timeout=15)
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    if revocation == "none":
        assert result["ok"], result
        binding = result["data"]
        assert restarted.store.list_automations() == [binding]
        assert binding["simulated"] and binding["enabled"]
    else:
        assert result["error"]["code"] == "NOUS_FORBIDDEN", result
        assert restarted.store.list_automations() == []
    assert restarted.store.list_runs() == []
    with restarted.store._db() as db:
        # A prepared immutable definition is not a published Automation or Work.
        assert (
            db.execute("SELECT COUNT(*) FROM workflow_definitions").fetchone()[0] == 1
        )
    with consumer.gate.store.operation_transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM governance_leases").fetchone()[0] == 0
        assert (
            db.execute("SELECT consumed FROM governance_human_nonces").fetchone()[0]
            == 1
        )
    replay = request(body, nonce, path)
    assert replay["error"]["code"] == (
        "NOUS_UNAUTHENTICATED" if revocation == "session" else "NOUS_CONTROL_REPLAY"
    )


@pytest.mark.parametrize("revocation", ["session", "expiry", "permission", "none"])
def test_http_trigger_revalidates_before_original_run_publication(
    consumer, automation_http, monkeypatch, revocation
):
    from nous_runtime.governance.permission import PermissionRule

    auth, context, request = automation_http
    binding = consumer.add_simulation(name="Original trigger admission")
    body = {
        "action": "trigger",
        "automation_id": binding["id"],
        "trigger_key": "original-human-trigger",
    }
    nonce = auth.nonce(context, "POST", "/api/v1/automations/action", body)["nonce"]
    writer_attempt = Event()
    blockers = []
    scoped = local()
    connect = WorkflowStore._connect
    claim = WorkflowStore.claim_automation_run

    def traced_connect(self):
        connection = connect(self)
        if getattr(scoped, "claim", False):
            connection.set_trace_callback(
                lambda sql: writer_attempt.set() if sql == "BEGIN IMMEDIATE" else None
            )
        return connection

    def held_claim(self, *args, **kwargs):
        # Hold exactly the initial claim, after HTTP/nonce admission. Later
        # reads of the original run must not create another writer barrier.
        if blockers:
            return claim(self, *args, **kwargs)
        blocker = sqlite3.connect(self.path, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")
        blockers.append(blocker)
        scoped.claim = True
        try:
            return claim(self, *args, **kwargs)
        finally:
            scoped.claim = False

    monkeypatch.setattr(WorkflowStore, "_connect", traced_connect)
    monkeypatch.setattr(WorkflowStore, "claim_automation_run", held_claim)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(request, body, nonce)
        try:
            assert writer_attempt.wait(timeout=10)
            assert not future.done()
            assert consumer.store.list_runs() == []
            if revocation == "session":
                auth.logout(context)
            elif revocation == "expiry":
                with consumer.gate.store.operation_transaction() as db:
                    db.execute(
                        "UPDATE governance_human_sessions SET expires_at=0 WHERE session_id=?",
                        (context.session_id,),
                    )
            elif revocation == "permission":
                auth.permissions.add(
                    PermissionRule(
                        "oidc:*:alice",
                        "control.automation.manage",
                        consumer.resource_id,
                        effect="deny",
                    )
                )
            if revocation != "none":
                with pytest.raises(PermissionError):
                    consumer.admit_management(context, audit=False)
            assert not future.done()
        finally:
            for blocker in blockers:
                blocker.rollback()
                blocker.close()
        result = future.result(timeout=15)
    restarted = AutomationConsumer(consumer.root, gate=consumer.gate)
    if revocation == "none":
        assert result["ok"], result
        assert result["data"]["state"] == "waiting_approval"
        runs = restarted.store.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == result["data"]["run_id"]
        assert all(count == 0 for count in result["data"]["effect_counts"].values())
    else:
        assert result["error"]["code"] == "NOUS_FORBIDDEN", result
        assert restarted.store.list_runs() == []
        assert restarted.store.automation_history(binding["id"]) == []
    with consumer.gate.store.operation_transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM governance_leases").fetchone()[0] == 0
        assert (
            db.execute("SELECT consumed FROM governance_human_nonces").fetchone()[0]
            == 1
        )
    replay = request(body, nonce)
    assert replay["error"]["code"] == (
        "NOUS_UNAUTHENTICATED"
        if revocation in {"session", "expiry"}
        else "NOUS_CONTROL_REPLAY"
    )


@pytest.mark.parametrize("boundary", ["observation-response", "commit-publication"])
def test_receipt_verified_original_requires_reconciliation_until_effect_commit(
    consumer, monkeypatch, boundary
):
    from nous_runtime.node_runtime.distributed_work import (
        DistributedWorkState,
        DistributedWorkStore,
    )
    from nous_runtime.node_runtime.relay import NodeRelayClient

    binding, pending = prepare(consumer)
    approve(consumer, pending)
    work_id = pending["outputs"]["mutate"]["work_id"]
    lost = []
    send = NodeRelayClient._send
    transition = DistributedWorkStore.transition

    async def lose_observation(self, websocket, message_type, payload, **kwargs):
        if message_type == "WORKLOAD_STATUS" and str(
            payload.get("workload_id", "")
        ).startswith("observe_"):
            lost.append(payload["output"]["observation_id"])
            return
        return await send(self, websocket, message_type, payload, **kwargs)

    def lose_commit(self, original_id, state, **kwargs):
        if original_id == work_id and state is DistributedWorkState.COMMITTED:
            lost.append("commit")
            raise OSError("controlled original effect commit publication failure")
        return transition(self, original_id, state, **kwargs)

    with monkeypatch.context() as fault:
        if boundary == "observation-response":
            fault.setattr(NodeRelayClient, "_send", lose_observation)
        else:
            fault.setattr(DistributedWorkStore, "transition", lose_commit)
        unresolved = consumer.resume(binding["id"], pending["run_id"])
    assert lost
    assert unresolved["state"] == "failed", unresolved
    original = next(work for work in unresolved["works"] if work["work_id"] == work_id)
    assert original["state"] == "VERIFIED"
    assert original["result_summary"]["remote_execution_receipt"]
    assert unresolved["effect_counts"][work_id] == 1
    if boundary == "observation-response":
        assert not original["effect_verification"]
    else:
        assert original["effect_verification"]["verdict"] == "MATCH"
    assert unresolved["reconciliation_required"] is True

    reconciled = consumer.reconcile(binding["id"], pending["run_id"])
    assert reconciled["run_id"] == pending["run_id"]
    assert reconciled["works"][-1]["state"] == "COMMITTED"
    assert reconciled["effect_counts"][work_id] == 1
    complete = consumer.resume(binding["id"], pending["run_id"])
    assert complete["state"] == "completed"
    assert complete["run_id"] == pending["run_id"]
    assert complete["outputs"]["mutate"]["work_id"] == work_id
    assert complete["effect_counts"][work_id] == 1
    assert not complete["reconciliation_required"]
    assert complete["outputs"]["mutate"]["effect_verification"]["verdict"] == "MATCH"
    assert {
        work["work_id"]
        for work in complete["works"]
        if work["execution_policy"].get("require_effect_verification")
    } == {work_id}
    if boundary == "observation-response":
        assert set(lost).isdisjoint(
            complete["outputs"]["mutate"]["effect_verification"]["observation_ids"]
        )
