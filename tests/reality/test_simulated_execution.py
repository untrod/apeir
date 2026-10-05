"""Hardware-independent contracts and real Node-protocol Reality acceptance."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from nous_runtime.agent import AgentSessionCoordinator, AgentSessionState
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.events.bus import RuntimeEventBus
from nous_runtime.core.errors import ArtifactError
from nous_runtime.governance import (
    ExecutionAuthorizationGate,
    GovernanceStore,
    GovernanceRequest,
    GrantScope,
)
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.credentials import CredentialBroker, VaultSecretBackend
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.node_runtime.distributed_work import (
    DistributedWork,
    DistributedWorkError,
    DistributedWorkState,
    DistributedWorkStore,
    WorkExecutionPolicy,
)
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import (
    NodeRuntimeConfig,
    NodeRuntimeService,
    WorkloadResponseLost,
)
from nous_runtime.planner.observation import Observation
from nous_runtime.reality import (
    DeviceLifecycle,
    DeviceRegistry,
    EffectVerdict,
    EffectVerifier,
    Operation,
    RealityOperationWorkflowHandler,
    ResourceGraph,
    ResourceKind,
    SimulatedDeviceOperationHandler,
    SimulatedDeviceProvider,
    SimulationFault,
)

pytestmark = pytest.mark.integration

DEFINITIONS = {
    "sim-actuator-001": {
        "device_type": "simulated-actuator",
        "capabilities": [
            "device.state.read",
            "device.state.set",
            "device.firmware.update",
        ],
        "state": {"enabled": False, "counter": 0, "firmware_version": "1.0.0"},
    }
}
STABLE = "sim-actuator-001"
WORK_ID = "work-simulated-effect"
RELAY_HEARTBEAT_SECONDS = 5
FAKE_CREDENTIAL = "apeir-m34b-reality-opaque-fixture-material-924681"
SECRET_HANDLE = "secret_" + "2" * 32


class Simulation:
    def __init__(
        self, root: Path, *, single_connection: bool = False, credentials=False
    ):
        self.root = root
        self.controller_state = root / "controller"
        self.bus = RuntimeEventBus(str(root))
        self.registry = DeviceRegistry(root / "devices", event_bus=self.bus)
        self.provider = SimulatedDeviceProvider(DEFINITIONS, state_dir=root / "device")
        self.governance = ExecutionAuthorizationGate(
            GovernanceStore(root / "governance")
        )
        self.credential_broker = None
        if credentials:
            self.secret_backend = VaultSecretBackend(
                root / "secret-backend" / "vault.db", master_key=b"s" * 32
            )
            self.secret_handle = self.secret_backend.put(SECRET_HANDLE, FAKE_CREDENTIAL)
            self.credential_broker = CredentialBroker(
                self.governance, self.secret_backend
            )
        self.node_handler = SimulatedDeviceOperationHandler(
            self.provider,
            self.registry,
            ContentAddressedArtifactStore(root / "node" / "artifacts"),
            governance=self.governance,
        )
        self.firmware_handler = SimulatedDeviceOperationHandler(
            self.provider,
            self.registry,
            ContentAddressedArtifactStore(root / "node" / "artifacts"),
            governance=self.governance,
            capability_id="device.firmware.update",
            credential_broker=self.credential_broker,
        )
        self.node = NodeRuntimeService(
            NodeRuntimeConfig(root / "node"),
            capability_handlers={
                "device.state.set": self.node_handler,
                "device.state.read": self.node_handler.read,
                "device.firmware.update": self.firmware_handler,
            },
        )
        device = self.provider.register_discovered(self.registry)[0]
        self.device = self.registry.register(
            replace(device, node_id=self.node.identity.node_id)
        )
        # M3.3 state-transition tests have explicit fixture-owned, bounded human
        # authority. Firmware updates have no fixture grant and must pause.
        fixture_request = GovernanceRequest(
            operation_id="fixture-state-authority",
            work_id="fixture-state-authority",
            capability_id="device.state.set",
            resource_id=self.device.device_id,
            subject_id="simulation-agent",
            node_id=self.node.identity.node_id,
            capability_inputs=self.governance.capability_inputs("device.state.set"),
        )
        self.governance.register_operation(fixture_request)
        self.governance.issue_operation_grant(
            fixture_request.authorization_id,
            _build_context(),
            scope=GrantScope.RESOURCE,
            max_uses=100,
        )
        if self.device.lifecycle is DeviceLifecycle.IDENTIFIED:
            self.registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
            self.device = self.registry.transition(
                device.device_id, DeviceLifecycle.AVAILABLE
            )
        self.server = self.controller()
        self.server.register_node(
            self.node.identity.node_id, self.node.identity.public_key
        )
        self.coordinator = AgentSessionCoordinator(root, event_bus=self.bus)
        self.handler = RealityOperationWorkflowHandler(
            self.controller_state,
            provider=self.provider,
            registry=self.registry,
            poll_interval_seconds=0.01,
            governance=self.governance,
        )
        self.single_connection = single_connection
        self.stop = asyncio.Event()

    def controller(self):
        return NodeRelayServer(
            state_dir=self.controller_state,
            artifact_store=ContentAddressedArtifactStore(
                self.controller_state / "artifacts"
            ),
            heartbeat_seconds=RELAY_HEARTBEAT_SECONDS,
        )

    async def start(self):
        url = await self.server.start()
        self.client = NodeRelayClient(
            self.node,
            url,
            self.server.public_key,
            heartbeat_seconds=RELAY_HEARTBEAT_SECONDS,
        )
        self.client_task = asyncio.create_task(
            self.client.run_session(self.stop)
            if self.single_connection
            else self.client.run_forever(self.stop)
        )
        await wait_for(
            lambda: (
                "RESOURCE_REPORT"
                in self.server.reports.get(self.node.identity.node_id, {})
            )
        )

    async def close(self):
        self.stop.set()
        self.client_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, OSError):
            await self.client_task
        await self.server.stop()
        self.coordinator.close()
        self.bus.shutdown()

    def plan(self, session, *, expected=True, wait_timeout=10):
        return TaskPlan(
            task_id=session.session_id,
            plan_id="plan-simulated-effect",
            steps=(
                PlanStep(
                    "mutate",
                    "Enable the simulated actuator",
                    "reality.operation",
                    metadata={
                        "device_id": self.device.device_id,
                        "capability": "device.state.set",
                        "work_id": WORK_ID,
                        "mutation": {"state": {"enabled": True}},
                        "expected_effect": {"enabled": expected},
                        "wait_timeout_seconds": wait_timeout,
                        "timeout_seconds": 30,
                    },
                ),
            ),
        )

    async def execute(self, *, expected=True, wait_timeout=10):
        session = self.coordinator.create(
            agent_id="simulation-agent",
            model="deterministic-planner",
            objective="Enable and independently verify the actuator",
            event_subscriptions=("reality.device.available",),
        )
        return await asyncio.to_thread(
            self.coordinator.coordinate,
            session.session_id,
            lambda current: self.plan(
                current, expected=expected, wait_timeout=wait_timeout
            ),
            handlers={"reality.operation": self.handler},
        )

    def work(self):
        work = DistributedWorkStore(self.controller_state).get(WORK_ID)
        assert work is not None
        return work


@asynccontextmanager
async def simulation(root: Path, **kwargs):
    sim = Simulation(root, **kwargs)
    await sim.start()
    try:
        yield sim
    finally:
        await sim.close()


async def wait_for(predicate, timeout=15):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("simulation condition did not converge")


def test_goal_plan_work_node_device_observation_effect_commit_provenance(tmp_path):
    async def scenario():
        async with simulation(tmp_path) as sim:
            completed = await sim.execute()
            assert completed.state is AgentSessionState.COMPLETED
            work = sim.work()
            assert work.state is DistributedWorkState.COMMITTED
            assert work.effect_verification["verdict"] == "MATCH"
            assert sim.provider.execution_count(WORK_ID) == 1
            assert work.provenance["agent_session_id"] == completed.session_id
            assert work.provenance["plan_id"] == completed.plan_history[0]["plan_id"]
            assert work.provenance["workflow_run_id"] == completed.workflow_run_id
            receipt = work.result_summary["remote_execution_receipt"]
            assert receipt["operation_id"] == WORK_ID
            assert receipt["node_id"] == sim.node.identity.node_id
            assert (
                receipt["target_ref"]
                == f"device://{sim.device.device_id}/capability/device.state.set"
            )
            reads = [
                item
                for item in DistributedWorkStore(sim.controller_state).list()
                if item.execution_capability == "device.state.read"
            ]
            assert len(reads) == 1
            assert reads[0].assigned_node == work.assigned_node
            assert reads[0].state is DistributedWorkState.COMMITTED
            observation = sim.controller().results[reads[0].work_id]["output"]
            assert observation["metadata"]["acquisition_id"] == reads[0].work_id
            assert (
                observation["observation_id"]
                in work.effect_verification["observation_ids"]
            )
            assert len(work.evidence_refs) == 3
            artifacts = ContentAddressedArtifactStore(
                sim.controller_state / "artifacts"
            )
            for reference in (
                *work.input_artifacts,
                *work.output_artifacts,
                *work.evidence_refs,
            ):
                assert artifacts.verify(digest(reference))
            mutation = json.loads(
                artifacts.resolve(digest(work.input_artifacts[0])).read_text()
            )
            assert mutation["provenance"]["agent_session_id"] == completed.session_id
            graph = ResourceGraph(sim.controller_state)
            assert graph.get(WORK_ID).attributes["node_id"] == sim.node.identity.node_id
            assert graph.get(sim.node.identity.node_id).kind is ResourceKind.NODE
            assert sim.node.artifact_store.verify(digest(work.input_artifacts[0]))
            assert sim.controller().reconcile_work(WORK_ID)["idempotent"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", [SimulationFault.DELAYED_RESULT, SimulationFault.DUPLICATE_RECEIPT]
)
def test_result_delay_and_duplicate_receipt_commit_once(tmp_path, fault):
    async def scenario():
        async with simulation(tmp_path) as sim:
            sim.provider.inject_fault(STABLE, fault, delay_seconds=0.03)
            completed = await sim.execute()
            assert completed.state is AgentSessionState.COMPLETED
            assert sim.work().state is DistributedWorkState.COMMITTED
            assert sim.provider.execution_count(WORK_ID) == 1
            assert sim.node._workloads[WORK_ID]["receipt"]["operation_id"] == WORK_ID

    asyncio.run(scenario())


def test_closed_artifact_connection_keeps_spool_alive_and_commits_once(
    tmp_path, monkeypatch
):
    from websockets.exceptions import ConnectionClosedError

    async def scenario():
        async with simulation(tmp_path) as sim:
            queue_artifact = sim.server.queue_artifact
            failures = 0

            async def disconnect_once(*args, **kwargs):
                nonlocal failures
                if failures == 0:
                    failures += 1
                    raise ConnectionClosedError(None, None)
                return await queue_artifact(*args, **kwargs)

            monkeypatch.setattr(sim.server, "queue_artifact", disconnect_once)
            completed = await sim.execute()
            assert completed.state is AgentSessionState.COMPLETED
            assert sim.work().state is DistributedWorkState.COMMITTED
            assert sim.provider.execution_count(WORK_ID) == 1
            assert failures == 1
            assert not sim.server._provider_spool_task.done()
            assert not (sim.server.provider_requests / f"{WORK_ID}.json").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", [SimulationFault.STALE_OBSERVATION, SimulationFault.DUPLICATE_OBSERVATION]
)
def test_stale_duplicate_observation_fails_closed_then_fresh_acquisition_recovers(
    tmp_path, fault
):
    async def scenario():
        async with simulation(tmp_path) as sim:
            sim.provider.read_state(sim.device)
            sim.provider.inject_fault(STABLE, fault)
            waiting = await sim.execute()
            assert waiting.state is AgentSessionState.WAITING
            assert WORK_ID in waiting.active_work
            assert sim.work().state is DistributedWorkState.VERIFIED
            assert sim.work().effect_verification["verdict"] == "UNKNOWN"
            prior_ids = sim.work().effect_verification["observation_ids"]
            recovered = await asyncio.to_thread(
                sim.coordinator.resume_plan,
                waiting.session_id,
                handlers={"reality.operation": sim.handler},
            )
            assert recovered.state is AgentSessionState.COMPLETED
            assert recovered.workflow_run_id == waiting.workflow_run_id
            assert sim.work().effect_verification["verdict"] == "MATCH"
            assert sim.work().effect_verification["observation_ids"] != prior_ids
            assert len(sim.work().evidence_refs) == 5
            assert sim.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


def test_mismatched_effect_keeps_work_uncommitted_and_session_waiting(tmp_path):
    async def scenario():
        async with simulation(tmp_path) as sim:
            waiting = await sim.execute(expected=False)
            assert waiting.state is AgentSessionState.WAITING
            assert sim.work().effect_verification["verdict"] == "MISMATCH"
            assert sim.work().state is DistributedWorkState.VERIFIED
            with pytest.raises(DistributedWorkError, match="independent MATCH"):
                DistributedWorkStore(sim.controller_state).transition(
                    WORK_ID, DistributedWorkState.COMMITTED, reason="skip reality"
                )
            assert sim.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", [SimulationFault.OPERATION_FAILURE, SimulationFault.DEVICE_DISCONNECT]
)
def test_operation_failure_disconnect_never_commit_or_reexecute(tmp_path, fault):
    async def scenario():
        async with simulation(tmp_path) as sim:
            sim.provider.inject_fault(STABLE, fault)
            waiting = await sim.execute()
            assert waiting.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0
            if fault is SimulationFault.DEVICE_DISCONNECT:
                assert (
                    sim.registry.get(sim.device.device_id).lifecycle
                    is DeviceLifecycle.OFFLINE
                )
                sim.provider.reconnect(STABLE, registry=sim.registry)
            await asyncio.to_thread(
                sim.coordinator.resume_plan,
                waiting.session_id,
                handlers={"reality.operation": sim.handler},
            )
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault, expected_count, expected_state",
    [
        (SimulationFault.EFFECT_THEN_RESPONSE_LOST, 1, DistributedWorkState.COMMITTED),
        (SimulationFault.LOST_RESPONSE, 0, DistributedWorkState.FAILED),
    ],
)
def test_response_loss_restart_reconciles_persisted_result_and_fresh_observation_without_replay(
    tmp_path, fault, expected_count, expected_state
):
    async def scenario():
        async with simulation(tmp_path, single_connection=True) as first:
            first.provider.inject_fault(STABLE, fault)
            waiting = await first.execute(wait_timeout=3)
            # Receipt persistence and connection loss are the recovery boundary;
            # filesystem speed is not evidence that the fault has occurred.
            await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == expected_count
            assert WORK_ID not in first.server.results
            assert first.client_task.done()
            assert isinstance(first.client_task.exception(), WorkloadResponseLost)
            assert first.node._workloads[WORK_ID]["receipt"]["operation_id"] == WORK_ID
            session_id = waiting.session_id
        async with simulation(tmp_path) as restored:
            recovered = await asyncio.to_thread(
                restored.coordinator.resume_plan,
                session_id,
                handlers={"reality.operation": restored.handler},
            )
            assert restored.work().state is expected_state
            assert restored.provider.execution_count(WORK_ID) == expected_count
            if expected_count:
                assert recovered.state is AgentSessionState.COMPLETED
                assert restored.work().effect_verification["verdict"] == "MATCH"
                assert len(restored.work().effect_verification["observation_ids"]) == 1
                assert (
                    restored.provider.read_state(restored.device).data["state"][
                        "enabled"
                    ]
                    is True
                )
            else:
                assert recovered.state is AgentSessionState.WAITING

    asyncio.run(scenario())


def test_device_available_event_wakes_restored_session_and_resumes_same_workflow(
    tmp_path,
):
    async def scenario():
        async with simulation(tmp_path) as first:
            first.provider.inject_fault(STABLE, SimulationFault.STALE_OBSERVATION)
            waiting = await first.execute()
            first.provider.disconnect(STABLE, registry=first.registry)
            assert (
                first.coordinator.require(waiting.session_id).state
                is AgentSessionState.WAITING
            )
            session_id = waiting.session_id
        # Discovery correctly excludes the offline device; reconnect via its stable identity.
        provider = SimulatedDeviceProvider(DEFINITIONS, state_dir=tmp_path / "device")
        provider.reconnect(STABLE)
        async with simulation(tmp_path) as restored:
            assert (
                restored.registry.get(restored.device.device_id).lifecycle
                is DeviceLifecycle.OFFLINE
            )
            restored.provider.reconnect(STABLE, registry=restored.registry)
            awake = restored.coordinator.require(session_id)
            assert awake.state is AgentSessionState.OBSERVING
            assert awake.observations[-1]["event_type"] == "reality.device.available"
            completed = await asyncio.to_thread(
                restored.coordinator.resume_plan,
                session_id,
                handlers={"reality.operation": restored.handler},
            )
            assert completed.state is AgentSessionState.COMPLETED
            assert completed.workflow_run_id == waiting.workflow_run_id
            assert restored.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


def test_revocation_and_identity_survive_disconnect_rediscovery_and_registry_restart(
    tmp_path,
):
    provider = SimulatedDeviceProvider(DEFINITIONS, state_dir=tmp_path / "device")
    registry = DeviceRegistry(tmp_path / "registry")
    device = provider.register_discovered(registry)[0]
    registry.transition(device.device_id, DeviceLifecycle.REVOKED)
    provider.disconnect(STABLE, registry=registry)
    provider.reconnect(STABLE, registry=DeviceRegistry(tmp_path / "registry"))
    restored = provider.register_discovered(DeviceRegistry(tmp_path / "registry"))[0]
    assert restored.device_id == device.device_id
    assert restored.lifecycle is DeviceLifecycle.REVOKED


@pytest.mark.parametrize(
    "lifecycle",
    [DeviceLifecycle.IDENTIFIED, DeviceLifecycle.TRUSTED, DeviceLifecycle.REVOKED],
)
def test_unavailable_devices_cannot_mutate_through_node(tmp_path, lifecycle):
    provider = SimulatedDeviceProvider(DEFINITIONS)
    registry = DeviceRegistry(tmp_path)
    device = provider.register_discovered(registry)[0]
    if lifecycle is not DeviceLifecycle.IDENTIFIED:
        device = registry.transition(device.device_id, lifecycle)
    handler = SimulatedDeviceOperationHandler(
        provider, registry, ContentAddressedArtifactStore(tmp_path / "artifacts")
    )
    with pytest.raises(RuntimeError, match="not available"):
        handler(
            {
                "operation": {
                    "operation_id": WORK_ID,
                    "target_resource_id": device.device_id,
                    "capability_id": "device.state.set",
                }
            }
        )
    assert provider.execution_count(WORK_ID) == 0


def test_receipt_verified_work_requires_match_even_on_controller_restart(tmp_path):
    store = DistributedWorkStore(tmp_path)
    work = store.create(
        DistributedWork(
            intent="Verify an effect",
            execution_policy=WorkExecutionPolicy(require_effect_verification=True),
        )
    )
    for state in [
        DistributedWorkState.SCHEDULED,
        DistributedWorkState.ASSIGNED,
        DistributedWorkState.RUNNING,
        DistributedWorkState.SUCCEEDED,
        DistributedWorkState.VERIFIED,
    ]:
        store.transition(
            work.work_id,
            state,
            reason="test",
            **(
                {"assigned_node": "node-test"}
                if state is DistributedWorkState.ASSIGNED
                else {}
            ),
        )
    with pytest.raises(DistributedWorkError, match="independent MATCH"):
        DistributedWorkStore(tmp_path).transition(
            work.work_id, DistributedWorkState.COMMITTED, reason="receipt alone"
        )


def test_failed_latest_and_conflicting_duplicate_observations_are_unknown():
    operation = Operation(
        WORK_ID,
        "device.state.set",
        "device-test",
        {"enabled": True},
        operation_id=WORK_ID,
    )
    receipt = {
        "schema": "nous.operation-receipt/v1",
        "operation_id": WORK_ID,
        "result": "COMPLETED",
        "effect_digest": "a" * 64,
    }
    fresh = Observation.success(
        "read", {"state": {"enabled": True}}, metadata={"device_id": "device-test"}
    )
    failed = Observation.failure(
        "read", ["offline"], metadata={"device_id": "device-test"}
    )
    assert (
        EffectVerifier().verify(operation, receipt, [fresh, failed]).verdict
        is EffectVerdict.UNKNOWN
    )
    conflicting = replace(fresh, data={"state": {"enabled": False}})
    assert (
        EffectVerifier().verify(operation, receipt, [fresh, conflicting]).verdict
        is EffectVerdict.UNKNOWN
    )
    duplicate = EffectVerifier().verify(operation, receipt, [fresh, fresh])
    assert duplicate.verdict is EffectVerdict.MATCH
    assert duplicate.observation_ids == (fresh.observation_id,)


def digest(reference):
    return "sha256:" + reference.removeprefix("artifact://sha256/")


def test_persisted_match_after_commit_interruption_recovers_without_mutation_or_new_observation(
    tmp_path, monkeypatch
):
    async def scenario():
        async with simulation(tmp_path) as sim:
            transition = DistributedWorkStore.transition

            def interrupt_commit(store, work_id, target, **kwargs):
                if work_id == WORK_ID and target is DistributedWorkState.COMMITTED:
                    raise OSError("injected commit interruption")
                return transition(store, work_id, target, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(DistributedWorkStore, "transition", interrupt_commit)
                waiting = await sim.execute()
            assert waiting.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.VERIFIED
            assert sim.work().effect_verification["verdict"] == "MATCH"
            observation_ids = sim.work().effect_verification["observation_ids"]
            completed = await asyncio.to_thread(
                sim.coordinator.resume_plan,
                waiting.session_id,
                handlers={"reality.operation": sim.handler},
            )
            assert completed.state is AgentSessionState.COMPLETED
            assert sim.work().effect_verification["observation_ids"] == observation_ids
            assert sim.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


def test_effect_with_missing_terminal_receipt_stays_unknown_after_restart_without_replay(
    tmp_path, monkeypatch
):
    from nous_runtime.node_runtime import service as node_service

    async def scenario():
        async with simulation(tmp_path, single_connection=True) as first:
            writer = node_service._atomic_write_json

            def lose_terminal(path, value):
                if (
                    path == first.node.workloads_path
                    and value.get(WORK_ID, {}).get("state") == "COMPLETED"
                ):
                    raise OSError("injected Node terminal journal failure")
                return writer(path, value)

            with monkeypatch.context() as patch:
                patch.setattr(node_service, "_atomic_write_json", lose_terminal)
                waiting = await first.execute(wait_timeout=3)
                await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 1
            session_id = waiting.session_id
        async with simulation(tmp_path) as restored:
            result = await asyncio.to_thread(
                restored.coordinator.resume_plan,
                session_id,
                handlers={"reality.operation": restored.handler},
            )
            assert result.state is AgentSessionState.WAITING
            assert restored.work().state is DistributedWorkState.UNKNOWN
            assert restored.provider.execution_count(WORK_ID) == 1
            assert restored.node._workloads[WORK_ID]["state"] == "EXECUTING"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "corruption", ["operation", "device", "capability", "artifact"]
)
def test_mutation_artifact_and_node_binding_corruption_fails_before_effect(
    tmp_path, corruption
):
    provider = SimulatedDeviceProvider(DEFINITIONS)
    registry = DeviceRegistry(tmp_path / "registry")
    device = provider.register_discovered(registry)[0]
    registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    device = registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)
    artifacts = ContentAddressedArtifactStore(tmp_path / "artifacts")
    value = {
        "schema": "apeir.reality-mutation-input/v1",
        "operation_id": WORK_ID,
        "device_id": device.device_id,
        "capability_id": "device.state.set",
        "mutation": {"state": {"enabled": True}},
    }
    if corruption != "artifact":
        value[
            {
                "operation": "operation_id",
                "device": "device_id",
                "capability": "capability_id",
            }[corruption]
        ] = "different"
    stored = artifacts.store_bytes(
        json.dumps(value).encode(), artifact_type="configuration", name="mutation.json"
    )
    reference = (
        f"artifact://sha256/{stored['artifact']['digest'].removeprefix('sha256:')}"
    )
    if corruption == "artifact":
        artifacts.resolve(digest(reference)).write_bytes(b"corrupt")
    handler = SimulatedDeviceOperationHandler(provider, registry, artifacts)
    with pytest.raises((ValueError, ArtifactError), match="binding|integrity"):
        handler(
            {
                "operation": {
                    "operation_id": WORK_ID,
                    "target_resource_id": device.device_id,
                    "capability_id": "device.state.set",
                },
                "mutation_artifact": reference,
            }
        )
    assert provider.execution_count(WORK_ID) == 0


def test_simulator_operation_binding_cannot_change_after_effect_and_restart(tmp_path):
    registry = DeviceRegistry(tmp_path / "registry")
    provider = SimulatedDeviceProvider(DEFINITIONS, state_dir=tmp_path / "device")
    device = provider.register_discovered(registry)[0]
    registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    device = registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)
    result = provider.apply_operation(
        device,
        operation_id=WORK_ID,
        capability_id="device.state.set",
        mutation={"state": {"enabled": True}},
    )
    restored = SimulatedDeviceProvider(DEFINITIONS, state_dir=tmp_path / "device")
    assert (
        restored.apply_operation(
            device,
            operation_id=WORK_ID,
            capability_id="device.state.set",
            mutation={"state": {"enabled": True}},
        )
        == result
    )
    with pytest.raises(ValueError, match="binding changed"):
        restored.apply_operation(
            device,
            operation_id=WORK_ID,
            capability_id="device.state.set",
            mutation={"state": {"enabled": False}},
        )
    assert restored.execution_count(WORK_ID) == 1


def test_unrelated_device_event_does_not_wake_targeted_session(tmp_path):
    bus = RuntimeEventBus(str(tmp_path))
    coordinator = AgentSessionCoordinator(tmp_path, event_bus=bus)
    try:
        session = coordinator.create(
            agent_id="device-agent",
            model="deterministic",
            objective="Wait for target device",
            context={"device_id": "device-target"},
            event_subscriptions=("reality.device.available",),
        )
        coordinator.wait(session.session_id)
        bus.publish("reality.device.available", payload={"device_id": "device-other"})
        assert (
            coordinator.require(session.session_id).state is AgentSessionState.WAITING
        )
        bus.publish("reality.device.available", payload={"device_id": "device-target"})
        assert (
            coordinator.require(session.session_id).state is AgentSessionState.OBSERVING
        )
    finally:
        coordinator.close()
        bus.shutdown()


def firmware_plan(sim, session, *, wait_timeout=10, expected="2.0.0"):
    return TaskPlan(
        task_id=session.session_id,
        plan_id="plan-firmware-upgrade",
        steps=(
            PlanStep(
                "inspect",
                "Detect outdated firmware",
                "reality.observe",
                metadata={
                    "device_id": sim.device.device_id,
                    "capability": "device.state.read",
                    "work_id": "firmware-inspect",
                    "wait_timeout_seconds": 10,
                    "timeout_seconds": 30,
                },
            ),
            PlanStep(
                "mutate",
                "Upgrade simulated firmware",
                "reality.operation",
                metadata={
                    "device_id": sim.device.device_id,
                    "capability": "device.firmware.update",
                    "work_id": WORK_ID,
                    "mutation": {"state": {"firmware_version": "2.0.0"}},
                    "expected_effect": {"firmware_version": expected},
                    **(
                        {"secret_handles": [SECRET_HANDLE]}
                        if sim.credential_broker
                        else {}
                    ),
                    "wait_timeout_seconds": wait_timeout,
                    "timeout_seconds": 30,
                },
            ),
        ),
        dependencies={"mutate": ("inspect",)},
    )


def firmware_handlers(sim):
    return {"reality.observe": sim.handler, "reality.operation": sim.handler}


async def request_firmware(sim, **kwargs):
    session = sim.coordinator.create(
        agent_id="simulation-agent",
        model="deterministic-planner",
        objective="Detect outdated firmware and upgrade to 2.0.0 with human authority",
    )
    paused = await asyncio.to_thread(
        sim.coordinator.coordinate,
        session.session_id,
        lambda current: firmware_plan(sim, current, **kwargs),
        handlers=firmware_handlers(sim),
    )
    assert paused.state is AgentSessionState.WAITING
    assert len(paused.pending_approvals) == 1
    assert sim.work().state is DistributedWorkState.CREATED
    assert sim.provider.execution_count(WORK_ID) == 0
    inspected = sim.server.results["firmware-inspect"]["output"]
    assert inspected["data"]["state"]["firmware_version"] == "1.0.0"
    return paused


async def resume_firmware(sim, session_id, **kwargs):
    return await asyncio.to_thread(
        sim.coordinator.resume_plan,
        session_id,
        handlers=firmware_handlers(sim),
        **kwargs,
    )


@pytest.mark.parametrize("restart", [False, True])
def test_firmware_approve_once_resumes_original_plan_work_and_commits_match(
    tmp_path, restart
):
    async def scenario():
        async with simulation(tmp_path) as first:
            paused = await request_firmware(first)
            original = first.work().to_dict()
            # Scheduler/Workflow hints are not approval authority.
            still_paused = await resume_firmware(
                first, paused.session_id, approved_steps=("mutate",)
            )
            assert still_paused.pending_approvals == paused.pending_approvals
            assert first.provider.execution_count(WORK_ID) == 0
            if not restart:
                await accept(first, paused, original)
        if restart:
            async with simulation(tmp_path) as restored:
                assert (
                    restored.coordinator.require(paused.session_id).pending_approvals
                    == paused.pending_approvals
                )
                await accept(restored, paused, original)

    async def accept(sim, paused, original):
        sim.handler.approvals.approve_operation_once(
            paused.pending_approvals[0],
            _build_context(),
            gate=sim.governance,
        )
        completed = await resume_firmware(sim, paused.session_id)
        work = sim.work()
        assert completed.state is AgentSessionState.COMPLETED
        assert completed.pending_approvals == ()
        assert completed.workflow_run_id == paused.workflow_run_id
        assert completed.plan_history == paused.plan_history
        assert work.execution_arguments == original["execution_arguments"]
        assert work.state is DistributedWorkState.COMMITTED
        assert work.effect_verification["verdict"] == "MATCH"
        assert sim.provider.execution_count(WORK_ID) == 1
        assert (
            sim.provider.read_state(sim.device).data["state"]["firmware_version"]
            == "2.0.0"
        )
        receipt = work.result_summary["remote_execution_receipt"]
        assert receipt["operation_id"] == WORK_ID
        assert receipt["node_id"] == sim.node.identity.node_id
        assert (
            receipt["target_ref"]
            == f"device://{sim.device.device_id}/capability/device.firmware.update"
        )
        rows = sim.governance.store.operation_audit()
        evidence = [
            json.loads(row["evidence_json"])
            for row in rows
            if row["decision_id"] == work.execution_arguments["authorization_id"]
        ]
        assert evidence
        for item in evidence:
            assert item["agent_session_id"] == completed.session_id
            assert item["workflow_run_id"] == completed.workflow_run_id
            assert item["plan_id"] == completed.plan_history[0]["plan_id"]
            assert item["work_id"] == item["operation_id"] == WORK_ID
            assert item["resource_id"] == sim.device.device_id
            assert item["input_artifacts"] == list(work.input_artifacts)
        events = {row["event_type"] for row in rows}
        assert {
            "approval.requested",
            "approval.decided",
            "grant.issued",
            "execution.admitted",
            "effect.verified",
        } <= events
        assert sim.governance.store.verify_audit_chain()

    asyncio.run(scenario())


@pytest.mark.parametrize("credentials", [False, True])
def test_firmware_deny_is_durable_and_never_changes_device(tmp_path, credentials):
    async def scenario():
        async with simulation(tmp_path, credentials=credentials) as first:
            paused = await request_firmware(first)
            if credentials:
                first.credential_broker.register_handle(
                    first.secret_handle,
                    first.work().execution_arguments["authorization_id"],
                    _build_context(),
                )
            first.handler.approvals.deny_operation(
                paused.pending_approvals[0],
                _build_context(),
                gate=first.governance,
            )
        async with simulation(tmp_path, credentials=credentials) as restored:
            if credentials:

                class UnavailableBackend:
                    def resolve(self, handle):
                        pytest.fail("Denied Work attempted credential resolution")

                restored.credential_broker._backend = UnavailableBackend()
            result = await resume_firmware(restored, paused.session_id)
            assert result.state is AgentSessionState.WAITING
            assert result.plan_history == paused.plan_history
            assert restored.work().state is DistributedWorkState.CREATED
            assert restored.provider.execution_count(WORK_ID) == 0
            assert (
                restored.provider.read_state(restored.device).data["state"][
                    "firmware_version"
                ]
                == "1.0.0"
            )
            assert (
                restored.governance.store.get_approval_request(
                    paused.pending_approvals[0]
                )["status"]
                == "DENIED"
            )
            assert not any(
                row["event_type"] == "execution.admitted"
                and row["decision_id"]
                == restored.work().execution_arguments["authorization_id"]
                for row in restored.governance.store.operation_audit()
            )

    asyncio.run(scenario())


def test_approved_firmware_lost_response_recovers_after_grant_revocation_without_replay(
    tmp_path,
):
    async def scenario():
        async with simulation(tmp_path, single_connection=True) as first:
            paused = await request_firmware(first, wait_timeout=3)
            first.provider.inject_fault(
                STABLE, SimulationFault.EFFECT_THEN_RESPONSE_LOST
            )
            first.handler.approvals.approve_operation_once(
                paused.pending_approvals[0],
                _build_context(),
                gate=first.governance,
            )
            waiting = await resume_firmware(first, paused.session_id)
            await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert isinstance(first.client_task.exception(), WorkloadResponseLost)
            assert first.provider.execution_count(WORK_ID) == 1
            assert WORK_ID not in first.server.results
            auth_id = first.work().execution_arguments["authorization_id"]
            with first.governance.store.operation_transaction() as db:
                grant_id = db.execute(
                    "SELECT lease_id FROM governance_leases WHERE proposal_hash=?",
                    (auth_id,),
                ).fetchone()[0]
            first.governance.revoke_operation_authority(
                auth_id, _build_context(), grant_id=grant_id
            )
        async with simulation(tmp_path) as restored:
            completed = await resume_firmware(restored, paused.session_id)
            assert completed.state is AgentSessionState.COMPLETED
            assert completed.workflow_run_id == paused.workflow_run_id
            assert restored.work().state is DistributedWorkState.COMMITTED
            assert restored.work().effect_verification["verdict"] == "MATCH"
            assert restored.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("credentials", [False, True])
def test_approved_firmware_missing_receipt_does_not_replay_even_with_valid_resource_grant(
    tmp_path, monkeypatch, credentials
):
    from nous_runtime.node_runtime import service as node_service

    async def scenario():
        async with simulation(
            tmp_path, single_connection=True, credentials=credentials
        ) as first:
            paused = await request_firmware(first, wait_timeout=3)
            auth_id = first.work().execution_arguments["authorization_id"]
            if credentials:
                first.credential_broker.register_handle(
                    first.secret_handle, auth_id, _build_context()
                )
            first.governance.issue_operation_grant(
                auth_id, _build_context(), scope=GrantScope.RESOURCE, max_uses=2
            )
            writer = node_service._atomic_write_json

            def lose_terminal(path, value):
                if (
                    path == first.node.workloads_path
                    and value.get(WORK_ID, {}).get("state") == "COMPLETED"
                ):
                    raise OSError("injected firmware terminal receipt loss")
                return writer(path, value)

            with monkeypatch.context() as patch:
                patch.setattr(node_service, "_atomic_write_json", lose_terminal)
                waiting = await resume_firmware(first, paused.session_id)
                await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 1
        async with simulation(tmp_path, credentials=credentials) as restored:
            if credentials:

                class UnavailableBackend:
                    def resolve(self, handle):
                        pytest.fail("Incomplete-journal recovery resolved credentials")

                restored.credential_broker._backend = UnavailableBackend()
            recovered = await resume_firmware(restored, paused.session_id)
            assert recovered.state is AgentSessionState.WAITING
            assert restored.work().state is DistributedWorkState.UNKNOWN
            assert restored.node._workloads[WORK_ID]["state"] == "EXECUTING"
            assert restored.provider.execution_count(WORK_ID) == 1
            if credentials:
                assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault,expected,verdict",
    [
        (None, "3.0.0", "MISMATCH"),
        (SimulationFault.STALE_OBSERVATION, "2.0.0", "UNKNOWN"),
    ],
)
def test_firmware_approval_cannot_commit_without_independent_match(
    tmp_path, fault, expected, verdict
):
    async def scenario():
        async with simulation(tmp_path) as sim:
            paused = await request_firmware(sim, expected=expected)
            if fault:
                sim.provider.inject_fault(STABLE, fault)
            sim.handler.approvals.approve_operation_once(
                paused.pending_approvals[0], _build_context(), gate=sim.governance
            )
            result = await resume_firmware(sim, paused.session_id)
            assert result.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.VERIFIED
            assert sim.work().effect_verification["verdict"] == verdict
            assert sim.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("revoke", ["grant", "resource"])
def test_node_rechecks_revocation_after_workflow_dispatch_approval(
    tmp_path, monkeypatch, revoke
):
    async def scenario():
        async with simulation(tmp_path) as sim:
            paused = await request_firmware(sim)
            auth_id = sim.work().execution_arguments["authorization_id"]
            sim.handler.approvals.approve_operation_once(
                paused.pending_approvals[0], _build_context(), gate=sim.governance
            )
            with sim.governance.store.operation_transaction() as db:
                grant_id = db.execute(
                    "SELECT lease_id FROM governance_leases WHERE proposal_hash=?",
                    (auth_id,),
                ).fetchone()[0]
            original = sim.firmware_handler.execute_bound

            def revoke_before_effect(arguments, **bindings):
                sim.governance.revoke_operation_authority(
                    auth_id,
                    _build_context(),
                    grant_id=grant_id,
                    resource=revoke == "resource",
                )
                return original(arguments, **bindings)

            monkeypatch.setattr(
                sim.firmware_handler, "execute_bound", revoke_before_effect
            )
            result = await resume_firmware(sim, paused.session_id)
            assert result.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0
            assert (
                sim.provider.read_state(sim.device).data["state"]["firmware_version"]
                == "1.0.0"
            )
            assert any(
                row["event_type"] == "execution.denied"
                for row in sim.governance.store.operation_audit()
            )

    asyncio.run(scenario())


def test_simulated_operation_cannot_bypass_node_admission(tmp_path):
    sim = Simulation(tmp_path)
    try:
        mutation = {
            "schema": "apeir.reality-mutation-input/v1",
            "operation_id": WORK_ID,
            "device_id": sim.device.device_id,
            "capability_id": "device.firmware.update",
            "mutation": {"state": {"firmware_version": "2.0.0"}},
        }
        stored = sim.node.artifact_store.store_bytes(
            json.dumps(mutation).encode(),
            artifact_type="configuration",
            name="mutation.json",
        )
        reference = (
            f"artifact://sha256/{stored['artifact']['digest'].removeprefix('sha256:')}"
        )
        with pytest.raises(PermissionError, match="Node"):
            sim.firmware_handler(
                {
                    "operation": {
                        "operation_id": WORK_ID,
                        "target_resource_id": sim.device.device_id,
                        "capability_id": "device.firmware.update",
                    },
                    "mutation_artifact": reference,
                }
            )
        assert sim.provider.execution_count(WORK_ID) == 0
    finally:
        sim.coordinator.close()
        sim.bus.shutdown()


def test_grant_expiring_during_provider_delay_is_rechecked_at_device_effect(
    tmp_path, monkeypatch
):
    from nous_runtime.governance import operation_gate
    from nous_runtime.reality import provider as provider_module

    async def scenario():
        async with simulation(tmp_path) as sim:
            paused = await request_firmware(sim)
            sim.handler.approvals.approve_operation_once(
                paused.pending_approvals[0], _build_context(), gate=sim.governance
            )
            delayed = []
            sleep = provider_module.time.sleep

            def expire_during_delay(seconds):
                if seconds == 3.14159:
                    delayed.append(True)
                    monkeypatch.setattr(
                        operation_gate, "_utc_now", lambda: "9999-01-01T00:00:00Z"
                    )
                else:
                    sleep(seconds)

            monkeypatch.setattr(provider_module.time, "sleep", expire_during_delay)
            sim.provider.inject_fault(
                STABLE, SimulationFault.DELAYED_RESULT, delay_seconds=3.14159
            )
            result = await resume_firmware(sim, paused.session_id)
            assert delayed == [True]
            assert result.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0
            assert any(
                json.loads(row["evidence_json"]).get("phase") == "before_effect"
                for row in sim.governance.store.operation_audit()
            )

    asyncio.run(scenario())


def approve_credential_firmware(sim, paused):
    auth_id = sim.work().execution_arguments["authorization_id"]
    sim.credential_broker.register_handle(sim.secret_handle, auth_id, _build_context())
    sim.handler.approvals.approve_operation_once(
        paused.pending_approvals[0], _build_context(), gate=sim.governance
    )
    return auth_id


def assert_no_credential_on_disk(root):
    for path in root.rglob("*"):
        if path.is_file():
            assert FAKE_CREDENTIAL.encode() not in path.read_bytes(), (
                f"Credential leaked into {path.relative_to(root)}"
            )


def test_credential_goal_firmware_operation_receipt_observation_commit_and_leakage(
    tmp_path, monkeypatch, caplog, capsys
):
    import logging
    import os
    import subprocess
    import sys
    from nous_runtime.core.redaction import REDACTED

    async def scenario():
        async with simulation(tmp_path, credentials=True) as sim:
            paused = await request_firmware(sim)
            auth_id = approve_credential_firmware(sim, paused)
            saved = []
            original = sim.provider.apply_operation

            def leaky_provider(device, **kwargs):
                context = kwargs["credential_context"]
                saved.append(context)
                value = context.get(SECRET_HANDLE)
                assert value == FAKE_CREDENTIAL
                assert not hasattr(context, "backend")
                with pytest.raises(PermissionError):
                    context.get("secret_" + "3" * 32)
                logging.getLogger("apeir.sim-credential").warning("Echo %s", value)
                print("Provider stdout " + value)
                child = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import os,sys; v=os.environ['APEIR_FAKE_OPERATION_KEY']; print(v); print(v,file=sys.stderr)",
                    ],
                    env={**os.environ, "APEIR_FAKE_OPERATION_KEY": value},
                    capture_output=True,
                    text=True,
                    check=True,
                )
                sim.bus.publish("provider.fixture.output", payload={"echo": value})
                sim.node.artifact_store.store_bytes(
                    b"safe fixture",
                    artifact_type="evidence",
                    name="safe.txt",
                    metadata={"echo": value},
                )
                return {
                    **original(device, **kwargs),
                    "provider_echo": value,
                    "subprocess": {"stdout": child.stdout, "stderr": child.stderr},
                    "provider_context": context,
                }

            monkeypatch.setattr(sim.provider, "apply_operation", leaky_provider)
            completed = await resume_firmware(sim, paused.session_id)
            assert completed.state is AgentSessionState.COMPLETED
            assert completed.plan_history == paused.plan_history
            assert completed.workflow_run_id == paused.workflow_run_id
            assert sim.work().state is DistributedWorkState.COMMITTED
            assert sim.work().effect_verification["verdict"] == "MATCH"
            assert sim.provider.execution_count(WORK_ID) == 1
            output = sim.node._workloads[WORK_ID]["output"]
            assert output["provider_echo"] == REDACTED
            assert output["provider_context"] == REDACTED
            assert FAKE_CREDENTIAL not in json.dumps(output)
            assert len(output["credential_lease_ids"]) == 1
            with pytest.raises(PermissionError, match="closed"):
                saved[0].get(SECRET_HANDLE)
            with sim.governance.store.operation_transaction() as db:
                row = db.execute(
                    "SELECT authorization_id,status,lease_json FROM governance_credential_leases"
                ).fetchone()
                assert row[0] == auth_id and row[1] == "CLOSED"
                assert json.loads(row[2])["node_id"] == sim.node.identity.node_id
            assert FAKE_CREDENTIAL not in json.dumps(completed.to_dict())
            assert_no_credential_on_disk(tmp_path)
        assert_no_credential_on_disk(tmp_path)

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    captured = capsys.readouterr()
    assert FAKE_CREDENTIAL not in captured.out + captured.err + caplog.text
    assert REDACTED in captured.out


def test_credential_provider_exception_cannot_leak_into_failed_receipt_or_events(
    tmp_path, monkeypatch
):
    async def scenario():
        async with simulation(tmp_path, credentials=True) as sim:
            paused = await request_firmware(sim)
            approve_credential_firmware(sim, paused)

            def failed_provider(device, **kwargs):
                raise RuntimeError(
                    "Provider failure: "
                    + kwargs["credential_context"].get(SECRET_HANDLE)
                )

            monkeypatch.setattr(sim.provider, "apply_operation", failed_provider)
            waiting = await resume_firmware(sim, paused.session_id)
            assert waiting.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0
            assert FAKE_CREDENTIAL not in json.dumps(sim.node._workloads[WORK_ID])
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


def test_credential_lost_response_recovers_without_resolving_revoked_delivery_again(
    tmp_path,
):
    class UnavailableBackend:
        calls = 0

        def resolve(self, handle):
            self.calls += 1
            raise AssertionError("Recovery must not resolve the mutation credential")

    async def scenario():
        async with simulation(
            tmp_path, credentials=True, single_connection=True
        ) as first:
            paused = await request_firmware(first, wait_timeout=3)
            auth_id = approve_credential_firmware(first, paused)
            first.provider.inject_fault(
                STABLE, SimulationFault.EFFECT_THEN_RESPONSE_LOST
            )
            waiting = await resume_firmware(first, paused.session_id)
            await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 1
            with first.governance.store.operation_transaction() as db:
                lease_id = db.execute(
                    "SELECT lease_id FROM governance_credential_leases"
                ).fetchone()[0]
            first.credential_broker.revoke(auth_id, _build_context(), lease_id=lease_id)
            first.credential_broker.revoke(
                auth_id, _build_context(), handle_id=SECRET_HANDLE
            )
            assert_no_credential_on_disk(tmp_path)
        async with simulation(tmp_path, credentials=True) as restored:
            backend = UnavailableBackend()
            restored.credential_broker._backend = backend
            completed = await resume_firmware(restored, paused.session_id)
            assert completed.state is AgentSessionState.COMPLETED
            assert restored.work().state is DistributedWorkState.COMMITTED
            assert restored.work().effect_verification["verdict"] == "MATCH"
            assert restored.provider.execution_count(WORK_ID) == 1
            assert backend.calls == 0
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


def test_disconnected_node_cannot_resolve_expired_handle_after_reconnect(tmp_path):
    async def scenario():
        async with simulation(tmp_path, credentials=True) as first:
            paused = await request_firmware(first, wait_timeout=3)
            approve_credential_firmware(first, paused)
            first.client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await first.client_task
            await wait_for(
                lambda: first.node.identity.node_id not in first.server.connections
            )
            waiting = await resume_firmware(first, paused.session_id)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 0
            with first.governance.store.operation_transaction() as db:
                db.execute(
                    "UPDATE governance_secret_handles SET expires_at='2000-01-01T00:00:00Z'"
                )
        async with simulation(tmp_path, credentials=True) as restored:
            waiting = await resume_firmware(restored, paused.session_id)
            assert waiting.state is AgentSessionState.WAITING
            assert restored.provider.execution_count(WORK_ID) == 0
            assert restored.work().state is DistributedWorkState.FAILED
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


def test_credential_expires_during_device_delay_and_blocks_effect(
    tmp_path, monkeypatch
):
    from datetime import datetime, timedelta, timezone
    from nous_runtime.governance import operation_gate
    from nous_runtime.reality import provider as provider_module

    async def scenario():
        async with simulation(tmp_path, credentials=True) as sim:
            paused = await request_firmware(sim)
            approve_credential_firmware(sim, paused)
            sleep = provider_module.time.sleep
            delayed = []

            def expire(seconds):
                if seconds == 3.14159:
                    delayed.append(True)
                    future = (
                        datetime.now(timezone.utc) + timedelta(seconds=60)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                    monkeypatch.setattr(operation_gate, "_utc_now", lambda: future)
                else:
                    sleep(seconds)

            monkeypatch.setattr(provider_module.time, "sleep", expire)
            sim.provider.inject_fault(
                STABLE, SimulationFault.DELAYED_RESULT, delay_seconds=3.14159
            )
            waiting = await resume_firmware(sim, paused.session_id)
            assert delayed == [True]
            assert waiting.state is AgentSessionState.WAITING
            assert sim.work().state is DistributedWorkState.FAILED
            assert sim.provider.execution_count(WORK_ID) == 0
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())
