from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.core.errors import ArtifactError
from nous_runtime.node_runtime.distributed_work import (
    DistributedWork,
    DistributedWorkState,
    WorkRequirements,
)
from nous_runtime.node_runtime.distributed_workflow import DistributedWorkflowAdapter
from nous_runtime.node_runtime.protocol import (
    NodeProtocolEnvelope,
    workload_request_digest,
)
from nous_runtime.node_runtime.relay import (
    CONTROL_PLANE_ID,
    NodeRelayClient,
    NodeRelayServer,
)
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStep,
)


def test_distributed_work_executes_verifies_artifacts_and_commits(tmp_path: Path):
    async def scenario() -> None:
        controller_state = tmp_path / "controller"
        controller_artifacts = ContentAddressedArtifactStore(
            controller_state / "artifacts"
        )
        server = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=controller_artifacts,
            heartbeat_seconds=0.5,
        )
        node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server.register_node(node.identity.node_id, node.identity.public_key)

        input_stored = controller_artifacts.store_bytes(
            b'{"message":"distributed-input"}',
            artifact_type="configuration",
            name="distributed-input.json",
            media_type="application/json",
            produced_by="test",
        )
        input_digest = str(input_stored["artifact"]["digest"])
        input_ref = f"artifact://sha256/{input_digest.removeprefix('sha256:')}"

        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(node, url, server.public_key, heartbeat_seconds=0.5)
        client_task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: (
                    "RESOURCE_REPORT" in server.reports.get(node.identity.node_id, {})
                )
            )
            assert server.work_store is not None
            server.work_store.create(
                DistributedWork(
                    work_id="work-distributed-e2e",
                    intent="Execute a governed remote echo",
                    creator="test-operator",
                    requirements=WorkRequirements(
                        architectures=(node.identity.platform_arch,),
                        operating_systems=(node.identity.platform_os,),
                        capabilities=("system.echo",),
                    ),
                    input_artifacts=(input_ref,),
                    execution_capability="system.echo",
                    execution_arguments={"message": "distributed-execution"},
                )
            )

            scheduled = server.schedule_work("work-distributed-e2e")
            assert scheduled["work"]["state"] == "ASSIGNED"
            assert scheduled["work"]["assignment"]["node_id"] == (node.identity.node_id)
            staged = server.stage_work_dispatch("work-distributed-e2e")
            assert staged["dispatch"]["delivery"] == "at_most_once"

            await _wait_for(
                lambda: (
                    _work_state(controller_state, "work-distributed-e2e") == "RUNNING"
                )
            )
            await _wait_for(lambda: "work-distributed-e2e" in server.results)
            assert server.results["work-distributed-e2e"]["state"] == "COMPLETED"
            assert node.artifact_store.verify(input_digest)
        finally:
            stop.set()
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
            await server.stop()

        restarted = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
        )
        reconciled = restarted.reconcile_work("work-distributed-e2e")
        work = reconciled["work"]
        assert work["state"] == DistributedWorkState.COMMITTED.value
        assert work["result_summary"]["status"] == "VERIFIED"
        assert work["result_summary"]["remote_execution_receipt"]["node_id"] == (
            node.identity.node_id
        )
        assert len(work["output_artifacts"]) == 1
        assert len(work["evidence_refs"]) == 1
        for reference in (*work["output_artifacts"], *work["evidence_refs"]):
            digest = "sha256:" + reference.removeprefix("artifact://sha256/")
            assert restarted.artifact_store is not None
            assert restarted.artifact_store.verify(digest)

        state_path = controller_state / "distributed-works.json"
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        persisted_work = persisted["works"]["work-distributed-e2e"]
        persisted_work["state"] = "VERIFIED"
        persisted_work["state_history"] = persisted_work["state_history"][:-1]
        state_path.write_text(
            json.dumps(persisted, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        recovered = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
        ).reconcile_work("work-distributed-e2e")
        assert recovered["work"]["state"] == "COMMITTED"
        assert recovered["idempotent"] is True

        duplicate = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
        ).reconcile_work("work-distributed-e2e")
        assert duplicate["idempotent"] is True
        assert duplicate["work"]["state"] == "COMMITTED"

    asyncio.run(scenario())


def test_uncertain_at_most_once_result_becomes_unknown_without_replay(
    tmp_path: Path,
):
    state_dir = tmp_path / "controller"
    server = NodeRelayServer(
        state_dir=state_dir,
        artifact_store=ContentAddressedArtifactStore(state_dir / "artifacts"),
    )
    node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    server.register_node(node.identity.node_id, node.identity.public_key)
    assert server.work_store is not None
    server.work_store.create(
        DistributedWork(
            work_id="work-uncertain",
            intent="Do not replay an uncertain effect",
            requirements=WorkRequirements(capabilities=("system.echo",)),
            execution_capability="system.echo",
            execution_arguments={"message": "once"},
        )
    )
    server.work_store.transition(
        "work-uncertain", DistributedWorkState.SCHEDULED, reason="test placement"
    )
    server.work_store.assign("work-uncertain", node.identity.node_id)
    server.stage_work_dispatch("work-uncertain")
    request = json.loads(
        (state_dir / "provider-requests" / "work-uncertain.json").read_text(
            encoding="utf-8"
        )
    )
    request_digest = workload_request_digest(
        request["capability"],
        request["arguments"],
        request["delivery_semantics"],
        request["binding"],
    )
    node._workloads["work-uncertain"] = {
        "workload_id": "work-uncertain",
        "capability": "system.echo",
        "state": "EXECUTING",
        "request_digest": request_digest,
        "binding": request["binding"],
        "delivery_semantics": "at_most_once",
    }
    payload = node.execute_workload(
        "work-uncertain",
        request["capability"],
        request["arguments"],
        delivery_semantics="at_most_once",
        binding=request["binding"],
    )
    assert payload["state"] == "RECOVERY_REQUIRED"
    envelope = NodeProtocolEnvelope(
        message_type="WORKLOAD_STATUS",
        source=node.identity.node_id,
        target=CONTROL_PLANE_ID,
        sequence=1,
        payload=payload,
        idempotency_key="work-uncertain",
    ).sign(node.load_private_key())
    server.results["work-uncertain"] = payload
    server.result_envelopes["work-uncertain"] = envelope.to_dict()
    server._save_workload_state()

    restarted = NodeRelayServer(
        state_dir=state_dir,
        artifact_store=ContentAddressedArtifactStore(state_dir / "artifacts"),
    )
    first = restarted.reconcile_work("work-uncertain")
    second = restarted.reconcile_work("work-uncertain")

    assert first["work"]["state"] == "UNKNOWN"
    assert second["work"]["state"] == "UNKNOWN"
    assert second["idempotent"] is True
    assert node._workloads["work-uncertain"]["state"] == "EXECUTING"


def test_dispatch_rejects_missing_input_and_recovers_staged_request(tmp_path: Path):
    state_dir = tmp_path / "controller"
    artifact_store = ContentAddressedArtifactStore(state_dir / "artifacts")
    server = NodeRelayServer(state_dir=state_dir, artifact_store=artifact_store)
    assert server.work_store is not None
    missing = "artifact://sha256/" + ("0" * 64)
    server.work_store.create(
        DistributedWork(
            work_id="work-missing-input",
            intent="Reject a missing input",
            requirements=WorkRequirements(capabilities=("system.echo",)),
            input_artifacts=(missing,),
            execution_capability="system.echo",
        )
    )
    server.work_store.transition(
        "work-missing-input",
        DistributedWorkState.SCHEDULED,
        reason="test placement",
    )
    server.work_store.assign("work-missing-input", "node-test")
    with pytest.raises(ArtifactError, match="artifact not found"):
        server.stage_work_dispatch("work-missing-input")

    artifact = server.artifact_store.store_bytes(
        b"input",
        artifact_type="configuration",
        name="input.txt",
        media_type="text/plain",
        produced_by="test",
    )
    digest = str(artifact["artifact"]["digest"])
    reference = f"artifact://sha256/{digest.removeprefix('sha256:')}"
    server.work_store.create(
        DistributedWork(
            work_id="work-recover-dispatch",
            intent="Recover a staged dispatch",
            requirements=WorkRequirements(capabilities=("system.echo",)),
            input_artifacts=(reference,),
            execution_capability="system.echo",
        )
    )
    server.work_store.transition(
        "work-recover-dispatch",
        DistributedWorkState.SCHEDULED,
        reason="test placement",
    )
    server.work_store.assign("work-recover-dispatch", "node-test")
    first = server.stage_work_dispatch("work-recover-dispatch")
    request_path = state_dir / "provider-requests" / "work-recover-dispatch.json"
    request_path.unlink()

    restarted = NodeRelayServer(
        state_dir=state_dir,
        artifact_store=ContentAddressedArtifactStore(state_dir / "artifacts"),
    )
    second = restarted.stage_work_dispatch("work-recover-dispatch")

    assert request_path.is_file()
    assert second["dispatch"] == first["dispatch"]


def test_existing_workflow_runs_verified_distributed_steps(tmp_path: Path):
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
        client = NodeRelayClient(node, url, server.public_key, heartbeat_seconds=0.5)
        client_task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: (
                    "RESOURCE_REPORT" in server.reports.get(node.identity.node_id, {})
                )
            )
            adapter = DistributedWorkflowAdapter(controller_state)
            runtime = WorkflowRuntime(
                str(tmp_path / "workflow"), handlers={"distributed": adapter}
            )
            definition = WorkflowDefinition(
                workflow_id="workflow.distributed-e2e",
                version="1.0.0",
                trigger=TriggerType.MANUAL,
                steps=(
                    WorkflowStep(
                        "prepare",
                        StepType.CAPABILITY,
                        "distributed",
                        timeout_seconds=10,
                        params={
                            "capability": "system.echo",
                            "arguments": {"message": "prepare"},
                            "wait_timeout_seconds": 5,
                        },
                    ),
                    WorkflowStep(
                        "consume",
                        StepType.CAPABILITY,
                        "distributed",
                        depends_on=("prepare",),
                        timeout_seconds=10,
                        params={
                            "capability": "system.echo",
                            "arguments": {"message": "consume"},
                            "input_from_steps": ["prepare"],
                            "wait_timeout_seconds": 5,
                        },
                    ),
                ),
            )
            runtime.register(definition)
            run = await asyncio.to_thread(
                runtime.start, definition.workflow_id, definition.version
            )

            assert run.state is WorkflowState.COMPLETED
            assert run.outputs["prepare"]["state"] == "COMMITTED"
            assert run.outputs["consume"]["state"] == "COMMITTED"
            assert run.outputs["consume"]["node_id"] == node.identity.node_id
            assert len(run.outputs["consume"]["output_artifacts"]) == 1
            assert node.artifact_store.verify(
                "sha256:"
                + run.outputs["prepare"]["output_artifacts"][0].removeprefix(
                    "artifact://sha256/"
                )
            )
        finally:
            stop.set()
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
            await server.stop()

    asyncio.run(scenario())


def _work_state(state_dir: Path, work_id: str) -> str:
    from nous_runtime.node_runtime.distributed_work import DistributedWorkStore

    work = DistributedWorkStore(state_dir).get(work_id)
    assert work is not None
    return work.state.value


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for distributed execution")
