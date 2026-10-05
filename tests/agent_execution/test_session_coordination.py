from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from nous_runtime.agent import AgentSessionCoordinator, AgentSessionState
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.events.bus import RuntimeEventBus
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.node_runtime.distributed_work import DistributedWorkState
from nous_runtime.node_runtime.distributed_workflow import DistributedWorkflowAdapter
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def test_event_subscription_wakes_waiting_session_after_restart(tmp_path: Path):
    first_bus = RuntimeEventBus(str(tmp_path))
    first = AgentSessionCoordinator(tmp_path, event_bus=first_bus)
    session = first.create(
        agent_id="operations-agent",
        model="test-model",
        objective="Recover an unavailable Node",
        event_subscriptions=("node.*",),
        budget={"max_work": 4},
        policy_scope={"nodes": ["node-jetson"]},
    )
    first.wait(session.session_id, reason="waiting for Node events")
    first.close()
    first_bus.shutdown()

    second_bus = RuntimeEventBus(str(tmp_path))
    second = AgentSessionCoordinator(tmp_path, event_bus=second_bus)
    second_bus.publish(
        "node.offline",
        source="node.runtime",
        payload={"node_id": "node-jetson"},
        event_id="evt_node_offline_once",
    )

    restored = second.require(session.session_id)
    assert restored.state is AgentSessionState.OBSERVING
    assert restored.budget == {"max_work": 4}
    assert restored.policy_scope == {"nodes": ["node-jetson"]}
    assert restored.observations[-1]["event_id"] == "evt_node_offline_once"

    # Event replay is idempotent for the session even if the bus sees it twice.
    second_bus.publish(
        "node.offline",
        source="node.runtime",
        payload={"node_id": "node-jetson"},
        event_id="evt_node_offline_once",
    )
    assert len(second.require(session.session_id).observations) == 1
    second.close()
    second_bus.shutdown()


def test_failed_workflow_becomes_evidence_and_can_be_replanned(tmp_path: Path):
    coordinator = AgentSessionCoordinator(tmp_path)
    session = coordinator.create(
        agent_id="engineering-agent",
        model="test-model",
        objective="Produce and verify an artifact",
    )
    first_plan = TaskPlan(
        task_id=session.session_id,
        steps=(PlanStep("attempt", "First attempt", "artifact.build"),),
    )

    def fail_handler(step, context):
        del step, context
        raise RuntimeError("input artifact was incomplete")

    second_plan = TaskPlan(
        task_id=session.session_id,
        steps=(PlanStep("retry", "Corrected attempt", "artifact.build"),),
    )
    observed_states = []
    completed = coordinator.coordinate(
        session.session_id,
        lambda current: first_plan,
        handlers={
            "artifact.build": lambda step, context: (
                fail_handler(step, context)
                if len(observed_states) == 0
                else {
                    "artifact": "artifact://sha256/output",
                    "verified": True,
                }
            )
        },
        replanner=lambda current: observed_states.append(current.state) or second_plan,
        max_replans=1,
    )

    assert completed.state is AgentSessionState.COMPLETED
    assert observed_states == [AgentSessionState.REPLANNING]
    assert len(completed.plan_history) == 2
    assert completed.result["workflow_outputs"]["retry"]["verified"] is True
    coordinator.close()


def test_approval_gate_resumes_same_durable_workflow(tmp_path: Path):
    coordinator = AgentSessionCoordinator(tmp_path)
    session = coordinator.create(
        agent_id="governed-agent",
        model="test-model",
        objective="Run an approved operation",
    )
    plan = TaskPlan(
        task_id=session.session_id,
        steps=(
            PlanStep("approve", "Human approval", "governance.approval"),
            PlanStep("execute", "Execute", "system.echo"),
        ),
        dependencies={"execute": ("approve",)},
    )
    waiting = coordinator.submit_plan(
        session.session_id,
        plan,
        handlers={"system.echo": lambda step, context: {"ok": True}},
    )

    assert waiting.state is AgentSessionState.WAITING
    assert waiting.pending_approvals == ("approve",)
    workflow_run_id = waiting.workflow_run_id

    completed = coordinator.resume_plan(
        session.session_id,
        approved_steps=("approve",),
        handlers={"system.echo": lambda step, context: {"ok": True}},
    )
    assert completed.state is AgentSessionState.COMPLETED
    assert completed.workflow_run_id == workflow_run_id
    assert completed.result["workflow_outputs"]["execute"] == {"ok": True}
    coordinator.close()


def test_plan_orchestrates_artifact_across_multiple_nodes(tmp_path: Path):
    coordinator = AgentSessionCoordinator(tmp_path)
    session = coordinator.create(
        agent_id="mesh-agent",
        model="test-model",
        objective="Prepare on Windows and process on Jetson",
        event_subscriptions=("workflow.*",),
    )
    plan = TaskPlan(
        task_id=session.session_id,
        steps=(
            PlanStep("prepare", "Prepare dataset", "mesh.prepare"),
            PlanStep("infer", "Run inference", "mesh.infer"),
            PlanStep("verify", "Verify result", "mesh.verify"),
        ),
        dependencies={"infer": ("prepare",), "verify": ("infer",)},
    )

    def prepare(step, context):
        del step, context
        return {
            "work_id": "work-windows-prepare",
            "node_id": "node-windows-amd64",
            "output_artifacts": ["artifact://sha256/dataset"],
        }

    def infer(step, context):
        del step
        assert context["outputs"]["prepare"]["output_artifacts"] == [
            "artifact://sha256/dataset"
        ]
        return {
            "work_id": "work-jetson-infer",
            "node_id": "node-jetson-arm64",
            "output_artifacts": ["artifact://sha256/inference"],
        }

    def verify(step, context):
        del step
        assert context["outputs"]["infer"]["node_id"] == "node-jetson-arm64"
        return {
            "work_id": "work-windows-verify",
            "node_id": "node-windows-amd64",
            "verified": True,
        }

    completed = coordinator.submit_plan(
        session.session_id,
        plan,
        handlers={
            "mesh.prepare": prepare,
            "mesh.infer": infer,
            "mesh.verify": verify,
        },
    )

    assert completed.state is AgentSessionState.COMPLETED
    assert set(completed.active_work) == {
        "work-windows-prepare",
        "work-jetson-infer",
        "work-windows-verify",
    }
    assert completed.result["workflow_outputs"]["verify"]["verified"] is True
    assert any(
        event["event_type"] == "workflow.completed"
        for event in completed.observations
        if event["kind"] == "workflow_event"
    )
    coordinator.close()


def test_agent_session_drives_verified_distributed_work(tmp_path: Path):
    async def scenario() -> None:
        controller_state = tmp_path / "controller"
        server = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
            heartbeat_seconds=0.5,
        )
        node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server.register_node(node.identity.node_id, node.identity.public_key)
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            node,
            url,
            server.public_key,
            heartbeat_seconds=0.5,
        )
        client_task = asyncio.create_task(client.run_forever(stop))
        coordinator = AgentSessionCoordinator(tmp_path / "coordination")
        try:
            await _wait_for(
                lambda: (
                    "RESOURCE_REPORT" in server.reports.get(node.identity.node_id, {})
                )
            )
            session = coordinator.create(
                agent_id="distributed-agent",
                model="test-model",
                objective="Execute and verify a governed Node operation",
            )
            plan = TaskPlan(
                task_id=session.session_id,
                steps=(
                    PlanStep(
                        "remote",
                        "Execute on an eligible Node",
                        "distributed",
                        metadata={
                            "capability": "system.echo",
                            "arguments": {"message": "m3-coordination"},
                            "wait_timeout_seconds": 5,
                            "timeout_seconds": 10,
                        },
                    ),
                ),
            )
            completed = await asyncio.to_thread(
                coordinator.submit_plan,
                session.session_id,
                plan,
                handlers={"distributed": DistributedWorkflowAdapter(controller_state)},
            )

            assert completed.state is AgentSessionState.COMPLETED
            assert len(completed.active_work) == 1
            assert server.work_store is not None
            work = server.work_store.get(completed.active_work[0])
            assert work is not None
            assert work.state is DistributedWorkState.COMMITTED
            assert work.assigned_node == node.identity.node_id
            assert work.output_artifacts
            assert work.evidence_refs
            assert work.result_summary["status"] == "VERIFIED"
            assert work.result_summary["remote_execution_receipt"]["node_id"] == (
                node.identity.node_id
            )
        finally:
            coordinator.close()
            stop.set()
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
            await server.stop()

    asyncio.run(scenario())


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition was not met before timeout")
