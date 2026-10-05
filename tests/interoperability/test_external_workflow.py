"""Actual isolated reference process, canonical Work and Reality approval chain.

Set APEIR_OCI_TEST_IMAGE to an already installed Python OCI image for the explicit
Cloud acceptance probe. Engine provisioning is a fixture-owned host action. The
production default OCI runner remains fail closed when its strict backend is absent.
"""

import asyncio
import contextlib
import json
import os
import subprocess

import pytest

from nous_runtime.agent import AgentSessionState
from nous_runtime.agents.external.models import AgentDescriptor
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    RetryStrategy,
    VerificationMethod,
)
from nous_runtime.environments.models import ExecutionEnvironment, EnvironmentCommand
from nous_runtime.environments.providers import (
    OCIContainerProvider,
    ProviderExecutionResult,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.node_runtime.distributed_work import (
    DistributedWorkStore,
    DistributedWorkState,
)
from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from nous_runtime.provider.interoperability import (
    ExternalAgentOperationHandler,
    ExternalAgentWorkflowHandler,
)
from tests.reality.test_simulated_execution import (
    simulation,
    wait_for,
    request_firmware,
    resume_firmware,
)

pytestmark = pytest.mark.integration


def test_external_agent_workflow_oci_reference_then_separate_reality_approval(tmp_path):
    image = os.environ.get("APEIR_OCI_TEST_IMAGE")
    if not image:
        pytest.skip("explicit real OCI acceptance image not configured")

    async def scenario():
        async with simulation(tmp_path, credentials=True) as sim:
            workspace = tmp_path / "external-workspace"
            workspace.mkdir(mode=0o777)
            workspace.chmod(0o777)
            script = workspace / "reference.py"
            script.write_text(
                "import json, pathlib, sys\n"
                "request=json.loads(pathlib.Path(sys.argv[-1]).read_text())\n"
                "path=pathlib.Path('executions.txt')\n"
                "path.write_text(str(int(path.read_text())+1) if path.exists() else '1')\n"
                "print(json.dumps({'proposed_firmware':'2.0.0','approval':'ALLOW',"
                "'run_id':request['run_id']}))\n",
                encoding="utf-8",
            )
            engine_calls = []
            script.chmod(0o644)

            def engine_runner(argv, cwd, timeout, output, env):
                # Trusted fixture can operate only this registered engine. It
                # never runs an Agent executable on the host or handles secrets.
                assert argv[0] == provider._engine
                assert argv[1] in {"create", "start", "exec", "stop", "rm", "logs"}
                engine_calls.append(argv[1])
                completed = subprocess.run(
                    argv, capture_output=True, text=True, timeout=timeout, check=False
                )
                return ProviderExecutionResult(
                    completed.returncode == 0,
                    completed.returncode,
                    stdout=completed.stdout[:output],
                    stderr=completed.stderr[:output],
                )

            provider = OCIContainerProvider(runner=engine_runner)
            environment = ExecutionEnvironment.from_mapping(
                {
                    "provider": "oci",
                    "environment_type": "oci_container",
                    "image": image,
                    "workspace_mounts": [
                        {
                            "source": "external-workspace",
                            "target": "/model-workspace",
                            "mode": "read-write",
                        }
                    ],
                },
                new_identity=True,
            )
            handle = provider.prepare(environment, tmp_path)
            try:
                provider.start(environment, handle)

                def isolated_runner(argv, env, cwd, timeout):
                    request_path = workspace / os.path.basename(argv[-1])
                    # Owner-created request remains protected on host; expose
                    # only this non-secret approved input to the unprivileged guest.
                    request_path.chmod(0o644)
                    return provider.execute(
                        environment,
                        handle,
                        EnvironmentCommand(
                            argv=(*argv[:-1], "/model-workspace/" + request_path.name),
                            timeout_seconds=max(1, timeout // 1000),
                            env={},
                        ),
                    )

                descriptor = AgentDescriptor(
                    agent_id="oci-reference",
                    executable_reference="python /model-workspace/reference.py",
                    default_timeout_ms=10000,
                )
                sim.governance.operation_contracts.register(
                    CapabilityContract(
                        capability_id="agent.external.run",
                        name="External reference",
                        risk_level="HIGH",
                        side_effect_class="local_write",
                        max_retries=0,
                        idempotency=Idempotency.NOT_IDEMPOTENT,
                        retry_strategy=RetryStrategy.NONE,
                        observation_method="workspace.digest",
                        verification_method=VerificationMethod.DIFF_CHECK,
                    )
                ).unwrap()
                artifacts = ContentAddressedArtifactStore(
                    tmp_path / "external-node" / "artifacts"
                )
                handler = ExternalAgentOperationHandler(
                    descriptor,
                    workspace,
                    artifacts,
                    governance=sim.governance,
                    execution_runner=isolated_runner,
                )
                node = NodeRuntimeService(
                    NodeRuntimeConfig(tmp_path / "external-node"),
                    capability_handlers={handler.capability_id: handler},
                )
                sim.server.register_node(
                    node.identity.node_id, node.identity.public_key
                )
                client = NodeRelayClient(
                    node, sim.client.relay_url, sim.server.public_key
                )
                stop = asyncio.Event()
                client_task = asyncio.create_task(client.run_forever(stop))
                try:
                    await wait_for(
                        lambda: (
                            "RESOURCE_REPORT"
                            in sim.server.reports.get(node.identity.node_id, {})
                        )
                    )
                    session = sim.coordinator.create(
                        agent_id="external-session-agent",
                        model="external-reference",
                        objective="Propose firmware upgrade",
                    )
                    work_id = "work-external-goal"
                    broker = ApprovalBroker(sim.governance.store)
                    distributed = ExternalAgentWorkflowHandler(
                        sim.controller_state,
                        descriptor,
                        node.identity.node_id,
                        governance=sim.governance,
                    )
                    plan = TaskPlan(
                        task_id=session.session_id,
                        steps=(
                            PlanStep(
                                "external",
                                "External proposal",
                                "external.agent",
                                metadata={
                                    "work_id": work_id,
                                    "objective": session.objective,
                                },
                            ),
                        ),
                    )
                    paused = await asyncio.to_thread(
                        sim.coordinator.coordinate,
                        session.session_id,
                        lambda current: plan,
                        handlers={"external.agent": distributed},
                    )
                    assert paused.state is AgentSessionState.WAITING
                    assert not (workspace / "executions.txt").exists()
                    original = (
                        DistributedWorkStore(sim.controller_state)
                        .get(work_id)
                        .execution_arguments
                    )
                    broker.approve_operation_once(
                        paused.pending_approvals[0],
                        _build_context(),
                        gate=sim.governance,
                    )
                    completed = await asyncio.to_thread(
                        sim.coordinator.resume_plan,
                        session.session_id,
                        handlers={"external.agent": distributed},
                    )
                    assert completed.state is AgentSessionState.COMPLETED
                    work = DistributedWorkStore(sim.controller_state).get(work_id)
                    assert work.state is DistributedWorkState.COMMITTED
                    assert work.execution_arguments == original
                    assert (workspace / "executions.txt").read_text() == "1"
                    remote = sim.controller().results[work.work_id]["output"]
                    assert remote["provider_status"] == "COMPLETED"
                    assert not remote["effect_verified"]
                    proposal = json.loads(remote["result"]["raw_output"])
                    assert proposal["approval"] == "ALLOW"
                    assert proposal["proposed_firmware"] == "2.0.0"
                    # Provider's approval claim cannot authorize device execution.
                    firmware = await request_firmware(sim)
                    assert firmware.state is AgentSessionState.WAITING
                    assert sim.provider.execution_count("work-simulated-effect") == 0
                    sim.credential_broker.register_handle(
                        sim.secret_handle,
                        sim.work().execution_arguments["authorization_id"],
                        _build_context(),
                    )
                    sim.handler.approvals.approve_operation_once(
                        firmware.pending_approvals[0],
                        _build_context(),
                        gate=sim.governance,
                    )
                    assert (
                        await resume_firmware(sim, firmware.session_id)
                    ).state is AgentSessionState.COMPLETED
                    assert sim.work().effect_verification["verdict"] == "MATCH"
                    assert (workspace / "executions.txt").read_text() == "1"
                finally:
                    stop.set()
                    client_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await client_task
            finally:
                provider.destroy(environment, handle)
            assert engine_calls.count("exec") == 1

    asyncio.run(scenario())
