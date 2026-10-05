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
        "capabilities": ["device.state.read", "device.state.set"],
        "state": {"enabled": False, "counter": 0},
    }
}
STABLE = "sim-actuator-001"
WORK_ID = "work-simulated-effect"
RELAY_HEARTBEAT_SECONDS = 5


class Simulation:
    def __init__(self, root: Path, *, single_connection: bool = False):
        self.root = root
        self.controller_state = root / "controller"
        self.bus = RuntimeEventBus(str(root))
        self.registry = DeviceRegistry(root / "devices", event_bus=self.bus)
        self.provider = SimulatedDeviceProvider(DEFINITIONS, state_dir=root / "device")
        self.node_handler = SimulatedDeviceOperationHandler(
            self.provider,
            self.registry,
            ContentAddressedArtifactStore(root / "node" / "artifacts"),
        )
        self.node = NodeRuntimeService(
            NodeRuntimeConfig(root / "node"),
            capability_handlers={
                "device.state.set": self.node_handler,
                "device.state.read": self.node_handler.read,
            },
        )
        device = self.provider.register_discovered(self.registry)[0]
        self.device = self.registry.register(
            replace(device, node_id=self.node.identity.node_id)
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
