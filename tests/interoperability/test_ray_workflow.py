"""Actual opt-in bounded Ray, same durable AgentSession and verified Reality.

The approved diagnostic exception is not a production PID default or physical
acceptance. The native Workflow, Governance, Node, CAS and verifier are reused.
"""

import asyncio
import contextlib
import json
import os
from dataclasses import replace

import pytest

from nous_runtime.agent import AgentSessionCoordinator, AgentSessionState
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    RetryStrategy,
    VerificationMethod,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.operation_contracts import GovernanceDecision
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.node_runtime.distributed_work import (
    DistributedWorkState,
    DistributedWorkStore,
)
from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from nous_runtime.provider.interoperability import (
    ExternalAgentOperationHandler,
    ExternalAgentWorkflowHandler,
)
from scripts.ci.ray_bounded_diagnostic import (
    RayBoundedDiagnostic,
    RayDiagnosticAdmissionRunner,
    RayDiagnosticProfile,
)
from tests.interoperability.test_external_agent import approve, execute, setup_agent
from tests.reality.test_simulated_execution import (
    FAKE_CREDENTIAL,
    WORK_ID,
    firmware_handlers,
    firmware_plan,
    simulation,
    wait_for,
)


def profile():
    image = os.environ.get("APEIR_RAY_DIAGNOSTIC_IMAGE")
    if not image:
        pytest.skip("explicit bounded Ray diagnostic image not configured")
    return RayDiagnosticProfile(
        image, int(os.environ.get("APEIR_RAY_DIAGNOSTIC_PIDS", "224")), True
    )


@pytest.mark.parametrize("prior", ["ready.json", "dispatch.json"])
def test_prior_dispatch_files_cannot_authorize_replay(tmp_path, prior):
    probe = RayBoundedDiagnostic(tmp_path, RayDiagnosticProfile("sha256:" + "1" * 64))
    (probe.workspace / prior).write_text("{}")
    with pytest.raises(PermissionError, match="replay"):
        probe.run()


@pytest.mark.parametrize(
    "case", ["valid", "deny", "cancel", "version", "profile", "bootstrap"]
)
def test_ready_dispatch_contract_without_engine(tmp_path, monkeypatch, case):
    probe = RayBoundedDiagnostic(tmp_path, RayDiagnosticProfile("sha256:" + "1" * 64))
    probe._expected_profile = probe.profile.to_dict()
    (probe.workspace / "ready.json").write_text(
        json.dumps({"version": "0.0.0" if case == "version" else "2.49.2"})
    )
    checked = []

    def check():
        checked.append("native revalidation")
        if case == "deny":
            raise PermissionError("revoked")

    probe._before_dispatch = check
    if case == "cancel":
        probe.cancel()
    if case == "profile":
        probe.profile = replace(probe.profile, pids=224, exception_acknowledged=True)
    if case == "bootstrap":
        from scripts.ci import ray_bounded_diagnostic

        monkeypatch.setattr(ray_bounded_diagnostic, "GUEST", "changed unapproved code")
    if case == "valid":
        probe._release_dispatch()
        assert checked == ["native revalidation"]
        assert json.loads((probe.workspace / "dispatch.json").read_text()) == {
            "dispatch": True
        }
    else:
        with pytest.raises(PermissionError):
            probe._release_dispatch()
        assert not (probe.workspace / "dispatch.json").exists()


@pytest.mark.parametrize("outcome", ["match", "deny", "mismatch", "unknown", "restart"])
def test_one_agent_session_ray_then_separate_firmware_authority(tmp_path, outcome):
    selected = profile()

    async def scenario():
        async with simulation(tmp_path, credentials=True) as sim:
            probe = RayBoundedDiagnostic(tmp_path / "ray", selected)
            runner = RayDiagnosticAdmissionRunner(probe)
            descriptor = runner.descriptor()
            sim.governance.operation_contracts.register(
                CapabilityContract(
                    capability_id="agent.external.run",
                    name="Bounded Ray qualification",
                    risk_level="HIGH",
                    side_effect_class="local_write",
                    idempotency=Idempotency.NOT_IDEMPOTENT,
                    retry_strategy=RetryStrategy.NONE,
                    verification_method=VerificationMethod.DIFF_CHECK,
                    observation_method="workspace.digest",
                    max_retries=0,
                )
            ).unwrap()
            node_root = tmp_path / "ray-node"
            handler = ExternalAgentOperationHandler(
                descriptor,
                probe.workspace,
                ContentAddressedArtifactStore(node_root / "artifacts"),
                governance=sim.governance,
                execution_runner=runner,
            )
            node = NodeRuntimeService(
                NodeRuntimeConfig(node_root),
                capability_handlers={handler.capability_id: handler},
            )
            sim.server.register_node(node.identity.node_id, node.identity.public_key)
            client = NodeRelayClient(node, sim.client.relay_url, sim.server.public_key)
            stop = asyncio.Event()
            task = asyncio.create_task(client.run_forever(stop))
            try:
                await wait_for(
                    lambda: (
                        "RESOURCE_REPORT"
                        in sim.server.reports.get(node.identity.node_id, {})
                    )
                )
                session = sim.coordinator.create(
                    agent_id="simulation-agent",
                    model="deterministic-planner",
                    objective="Inspect old firmware, qualify Ray execution and upgrade with authority",
                )
                base = firmware_plan(
                    sim, session, expected="9.9.9" if outcome == "mismatch" else "2.0.0"
                )
                ray_step = PlanStep(
                    "ray",
                    "Qualify Ray before device mutation",
                    "external.agent",
                    metadata={
                        "work_id": "ray-work",
                        "timeout_ms": 45000,
                        "wait_timeout_seconds": 60,
                    },
                )
                plan = TaskPlan(
                    task_id=session.session_id,
                    plan_id="plan-ray-firmware",
                    steps=(base.steps[0], ray_step, base.steps[1]),
                    dependencies={"ray": ("inspect",), "mutate": ("ray",)},
                )
                handlers = {
                    **firmware_handlers(sim),
                    "external.agent": ExternalAgentWorkflowHandler(
                        sim.controller_state,
                        descriptor,
                        node.identity.node_id,
                        governance=sim.governance,
                    ),
                }
                paused = await asyncio.to_thread(
                    sim.coordinator.coordinate,
                    session.session_id,
                    lambda _: plan,
                    handlers=handlers,
                )
                assert paused.state is AgentSessionState.WAITING
                assert not probe.handle
                assert sim.provider.execution_count(WORK_ID) == 0
                store = DistributedWorkStore(sim.controller_state)
                original = store.get("ray-work").execution_arguments
                broker = ApprovalBroker(sim.governance.store)
                broker.approve_operation_once(
                    paused.pending_approvals[0], _build_context(), gate=sim.governance
                )
                paused = await asyncio.to_thread(
                    sim.coordinator.resume_plan, session.session_id, handlers=handlers
                )
                assert paused.state is AgentSessionState.WAITING
                assert paused.session_id == session.session_id
                assert store.get("ray-work").execution_arguments == original
                assert store.get("ray-work").state is DistributedWorkState.COMMITTED
                remote = sim.controller().results["ray-work"]["output"]
                assert not remote["effect_verified"]
                digest = "sha256:" + remote["result_artifact"].removeprefix(
                    "artifact://sha256/"
                )
                cas = ContentAddressedArtifactStore(node_root / "artifacts")
                assert cas.verify(digest)
                provenance = cas.get(digest).metadata
                assert provenance["agent_session_id"] == session.session_id
                assert provenance["plan_id"] == plan.plan_id
                assert provenance["work_id"] == "ray-work"
                assert provenance["authorization_id"] == original["authorization_id"]
                assert provenance["trust"] == "untrusted-provider-result"
                evidence = json.loads(remote["result"]["raw_output"])
                assert evidence["run_id"] == "ray-work"
                assert evidence["ray_task"]["effect_count"] == "1"
                assert probe.report["dispatch_admission"] == {
                    "ray_ready": True,
                    "governed": True,
                }
                assert probe.report["cleanup"]["container_absent"]
                assert probe.report["cleanup"]["execution_thread_stopped"]
                assert not probe.report["cleanup"]["remaining_host_processes"]
                assert sim.provider.execution_count(WORK_ID) == 0
                firmware = store.get(WORK_ID)
                assert (
                    firmware.execution_arguments["operation"]["agent_session_id"]
                    == session.session_id
                )
                original_firmware = firmware.execution_arguments
                if outcome == "restart":
                    # Reload both durable Workflow/Session state and the Ray
                    # Node journal. Original Work and consumed approval survive.
                    stop.set()
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    sim.coordinator.close()
                    sim.coordinator = AgentSessionCoordinator(
                        sim.root, event_bus=sim.bus
                    )
                    restored = NodeRuntimeService(
                        NodeRuntimeConfig(node_root),
                        capability_handlers={handler.capability_id: handler},
                    )
                    assert restored.identity.node_id == node.identity.node_id
                    assert restored._workloads["ray-work"]["state"] == "COMPLETED"
                    assert (
                        sim.coordinator.require(session.session_id).pending_approvals
                        == paused.pending_approvals
                    )
                    client = NodeRelayClient(
                        restored, sim.client.relay_url, sim.server.public_key
                    )
                    stop = asyncio.Event()
                    task = asyncio.create_task(client.run_forever(stop))
                if outcome == "deny":
                    broker.deny_operation(
                        paused.pending_approvals[0],
                        _build_context(),
                        gate=sim.governance,
                    )
                else:
                    sim.credential_broker.register_handle(
                        sim.secret_handle,
                        firmware.execution_arguments["authorization_id"],
                        _build_context(),
                    )
                    broker.approve_operation_once(
                        paused.pending_approvals[0],
                        _build_context(),
                        gate=sim.governance,
                    )
                    if outcome == "unknown":
                        from nous_runtime.reality import SimulationFault

                        sim.provider.read_state(sim.device)
                        sim.provider.inject_fault(
                            sim.device.stable_identity,
                            SimulationFault.STALE_OBSERVATION,
                        )
                completed = await asyncio.to_thread(
                    sim.coordinator.resume_plan, session.session_id, handlers=handlers
                )
                assert store.get(WORK_ID).execution_arguments == original_firmware
                if outcome in {"match", "restart"}:
                    assert completed.state is AgentSessionState.COMPLETED
                    assert store.get(WORK_ID).state is DistributedWorkState.COMMITTED
                    assert store.get(WORK_ID).effect_verification["verdict"] == "MATCH"
                    assert sim.provider.execution_count(WORK_ID) == 1
                elif outcome == "deny":
                    assert completed.state is not AgentSessionState.COMPLETED
                    assert sim.provider.execution_count(WORK_ID) == 0
                    assert (
                        sim.provider.read_state(sim.device).data["state"][
                            "firmware_version"
                        ]
                        == "1.0.0"
                    )
                else:
                    assert completed.state is not AgentSessionState.COMPLETED
                    assert (
                        store.get(WORK_ID).state is not DistributedWorkState.COMMITTED
                    )
                    assert (
                        store.get(WORK_ID).effect_verification["verdict"]
                        == outcome.upper()
                    )
                    assert sim.provider.execution_count(WORK_ID) == 1
                assert (probe.workspace / "count.txt").read_text() == "1"
                # No fake broker material may enter Ray telemetry, Work or CAS.
                for root in (
                    probe.root,
                    sim.controller_state,
                    node_root,
                    sim.root / "governance",
                ):
                    for path in root.rglob("*"):
                        if path.is_file():
                            assert FAKE_CREDENTIAL.encode() not in path.read_bytes()
            finally:
                stop.set()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["deny", "unknown", "expiry", "profile"])
def test_actual_ray_ready_then_authority_revalidation_prevents_task(
    tmp_path, monkeypatch, failure
):
    from types import SimpleNamespace
    from nous_runtime.governance import operation_gate

    probe = RayBoundedDiagnostic(tmp_path, profile())
    runner = RayDiagnosticAdmissionRunner(probe)
    policy = SimpleNamespace(evaluate=lambda request: GovernanceDecision.ALLOW)
    fixture = setup_agent(
        tmp_path,
        runner,
        policy=policy,
        descriptor=runner.descriptor(),
        timeout_ms=45000,
    )
    release = probe._release_dispatch

    def change_then_release():
        assert (probe.workspace / "ready.json").exists()
        if failure in {"deny", "unknown"}:
            policy.evaluate = lambda request: GovernanceDecision(failure.upper())
        elif failure == "expiry":
            monkeypatch.setattr(
                operation_gate, "_utc_now", lambda: "9999-12-31T23:59:59Z"
            )
        else:
            probe.profile = replace(probe.profile, pids=256)
        release()

    monkeypatch.setattr(probe, "_release_dispatch", change_then_release)
    approve(fixture)
    assert execute(fixture)["state"] == "FAILED"
    assert (probe.workspace / "ready.json").exists()
    assert not (probe.workspace / "count.txt").exists()
    assert not (probe.workspace / "dispatch.json").exists()
    assert probe.report["cleanup"]["container_absent"]
    assert probe.report["cleanup"]["execution_thread_stopped"]
    assert execute(fixture)["state"] == "FAILED"
