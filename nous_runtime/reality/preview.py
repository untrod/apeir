"""Credential-free local demo composing existing Runtime authorities.

The simulator is a built-in bounded device handler, not an arbitrary script or
sandbox substitute. All effects still use Governance, Workflow, signed Node
delivery, CAS, independent read Work and the existing MATCH-only finalizer.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from pathlib import Path

from nous_runtime.agent import AgentSessionCoordinator
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.events.bus import RuntimeEventBus
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.locking import file_lock
from nous_runtime.node_runtime.distributed_work import DistributedWorkStore
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import (
    NodeRuntimeConfig,
    NodeRuntimeService,
    WorkloadResponseLost,
)
from nous_runtime.reality import (
    DeviceLifecycle,
    DeviceRegistry,
    RealityOperationWorkflowHandler,
    SimulatedDeviceOperationHandler,
    SimulatedDeviceProvider,
    SimulationFault,
)

SCENARIOS = ("match", "deny", "mismatch", "unknown", "lost-response", "restart")
WORK_ID = "preview-firmware-update"
AGENT_ID = "developer-preview-agent"
STABLE_ID = "preview-simulated-device"
DEFINITION = {
    STABLE_ID: {
        "device_type": "simulated-actuator",
        "capabilities": ["device.state.read", "device.firmware.update"],
        "state": {"firmware_version": "1.0.0", "enabled": False},
    }
}


async def _wait(predicate, timeout=15):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError("Demo did not observe the required Runtime transition")


class _DemoComponents:
    """Local lifecycle wrapper only; each mutable state keeps its existing owner."""

    def __init__(self, root: Path, *, response_loss=False):
        self.bus = None
        self.coordinator = None
        try:
            self._initialize(root, response_loss=response_loss)
        except BaseException:
            if self.coordinator is not None:
                self.coordinator.close()
            if self.bus is not None:
                self.bus.shutdown()
            raise

    def _initialize(self, root: Path, *, response_loss=False):
        self.root = root
        self.state = root / ".nous"
        self.controller_state = self.state / "relay"
        self.bus = RuntimeEventBus(str(root))
        self.registry = DeviceRegistry(self.state / "reality", event_bus=self.bus)
        self.provider = SimulatedDeviceProvider(
            DEFINITION, state_dir=self.state / "simulated-device"
        )
        self.gate = ExecutionAuthorizationGate(GovernanceStore(self.state))
        artifacts = ContentAddressedArtifactStore(self.state / "node" / "artifacts")
        firmware = SimulatedDeviceOperationHandler(
            self.provider,
            self.registry,
            artifacts,
            governance=self.gate,
            capability_id="device.firmware.update",
        )
        self.node = NodeRuntimeService(
            NodeRuntimeConfig(self.state / "node"),
            capability_handlers={
                "device.firmware.update": firmware,
                "device.state.read": firmware.read,
            },
        )
        discovered = self.provider.register_discovered(self.registry)[0]
        self.device = self.registry.register(
            replace(discovered, node_id=self.node.identity.node_id)
        )
        # Explicit local demo enrollment. Rediscovery does not revive revocation.
        if self.device.lifecycle is DeviceLifecycle.IDENTIFIED:
            self.registry.transition(self.device.device_id, DeviceLifecycle.TRUSTED)
            self.device = self.registry.transition(
                self.device.device_id, DeviceLifecycle.AVAILABLE
            )
        self.server = NodeRelayServer(
            state_dir=self.controller_state,
            artifact_store=ContentAddressedArtifactStore(
                self.controller_state / "artifacts"
            ),
            heartbeat_seconds=5,
        )
        self.server.register_node(
            self.node.identity.node_id, self.node.identity.public_key
        )
        self.coordinator = AgentSessionCoordinator(root, event_bus=self.bus)
        self.handler = RealityOperationWorkflowHandler(
            self.controller_state,
            provider=self.provider,
            registry=self.registry,
            governance=self.gate,
            poll_interval_seconds=0.02,
        )
        self.handlers = {
            "reality.observe": self.handler,
            "reality.operation": self.handler,
        }
        self.response_loss = response_loss
        self.stop = asyncio.Event()
        self.client_task = None

    async def start(self):
        url = await self.server.start()
        client = NodeRelayClient(
            self.node, url, self.server.public_key, heartbeat_seconds=5
        )
        self.client_task = asyncio.create_task(
            client.run_session(self.stop)
            if self.response_loss
            else client.run_forever(self.stop)
        )
        await _wait(
            lambda: (
                "RESOURCE_REPORT"
                in self.server.reports.get(self.node.identity.node_id, {})
            )
        )

    async def close(self):
        self.stop.set()
        try:
            if self.client_task is not None:
                self.client_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, OSError):
                    await self.client_task
        finally:
            try:
                await self.server.stop()
            finally:
                self.coordinator.close()
                self.bus.shutdown()

    def work(self):
        return DistributedWorkStore(self.controller_state).get(WORK_ID)

    def plan(self, session, scenario):
        return TaskPlan(
            task_id=session.session_id,
            plan_id="preview-firmware-plan",
            steps=(
                PlanStep(
                    "inspect",
                    "Observe simulated firmware",
                    "reality.observe",
                    metadata={
                        "device_id": self.device.device_id,
                        "capability": "device.state.read",
                        "work_id": "preview-firmware-inspect",
                        "wait_timeout_seconds": 15,
                        "timeout_seconds": 60,
                    },
                ),
                PlanStep(
                    "mutate",
                    "Update simulated firmware to 2.0.0",
                    "reality.operation",
                    metadata={
                        "device_id": self.device.device_id,
                        "capability": "device.firmware.update",
                        "work_id": WORK_ID,
                        "mutation": {"state": {"firmware_version": "2.0.0"}},
                        "expected_effect": {
                            "firmware_version": "3.0.0"
                            if scenario == "mismatch"
                            else "2.0.0"
                        },
                        "wait_timeout_seconds": 1
                        if scenario == "lost-response"
                        else 15,
                        "timeout_seconds": 60,
                    },
                ),
            ),
            dependencies={"mutate": ("inspect",)},
        )

    async def prepare(self, scenario):
        session = self.coordinator.create(
            agent_id=AGENT_ID,
            model="deterministic-demo-planner",
            objective="Observe, govern, update and independently verify simulated firmware",
            context={"demo_scenario": scenario, "simulated": True},
        )
        return await asyncio.to_thread(
            self.coordinator.coordinate,
            session.session_id,
            lambda current: self.plan(current, scenario),
            handlers=self.handlers,
        )

    async def resume(self, session):
        return await asyncio.to_thread(
            self.coordinator.resume_plan,
            session.session_id,
            handlers=self.handlers,
        )

    def projection(self, session):
        work = self.work()
        if work is None:
            raise ValueError("Original demo Work is missing")
        refs = (*work.input_artifacts, *work.output_artifacts, *work.evidence_refs)
        cas = ContentAddressedArtifactStore(self.controller_state / "artifacts")
        for ref in refs:
            if not cas.verify("sha256:" + ref.removeprefix("artifact://sha256/")):
                raise ValueError("Demo Artifact integrity failed")
        reads = [
            w
            for w in DistributedWorkStore(self.controller_state).list()
            if w.execution_capability == "device.state.read"
        ]
        plane = OperationsPlane(
            self.root,
            gate=self.gate,
            controller=self.server,
            controller_state=self.controller_state,
            device_state=self.registry.state_dir,
        )
        return {
            "execution_scope": "runtime-service",
            "kernel_traversed": False,
            "simulated": True,
            "projection_only": True,
            "agent_session": session.to_dict(),
            "work": work.to_dict(),
            "receipt": work.result_summary.get("remote_execution_receipt"),
            "observations": [
                {
                    "work_id": w.work_id,
                    "state": w.state.value,
                    "output": self.server.results.get(w.work_id, {}).get("output"),
                }
                for w in reads
            ],
            "effect_verification": dict(work.effect_verification),
            "effect_count": self.provider.execution_count(WORK_ID),
            "artifact_integrity_checked": len(refs),
            "operations": plane.snapshot(),
        }


async def _run(root, scenario, phase, approval_context):
    components = _DemoComponents(
        root, response_loss=scenario == "lost-response" and phase != "resume"
    )
    try:
        await components.start()
        if phase == "resume":
            sessions = [
                s for s in components.coordinator.store.list() if s.agent_id == AGENT_ID
            ]
            if len(sessions) != 1:
                raise ValueError("Resume requires exactly one original demo session")
            session = sessions[0]
            scenario = session.context["demo_scenario"]
        else:
            session = await components.prepare(scenario)
        if phase == "prepare" or approval_context is None:
            return components.projection(session)
        if scenario == "restart" and phase != "resume":
            await components.close()
            components = _DemoComponents(root)
            await components.start()
            session = components.coordinator.require(session.session_id)
        if session.pending_approvals:
            if scenario == "deny":
                components.handler.approvals.deny_operation(
                    session.pending_approvals[0],
                    approval_context,
                    gate=components.gate,
                )
            else:
                components.handler.approvals.approve_operation_once(
                    session.pending_approvals[0],
                    approval_context,
                    gate=components.gate,
                )
            if scenario == "unknown":
                components.provider.inject_fault(
                    STABLE_ID, SimulationFault.STALE_OBSERVATION
                )
            if scenario == "lost-response" and phase != "resume":
                components.provider.inject_fault(
                    STABLE_ID, SimulationFault.EFFECT_THEN_RESPONSE_LOST
                )
        original = session
        session = await components.resume(session)
        if scenario == "lost-response" and phase != "resume":
            await _wait(components.client_task.done)
            if not isinstance(components.client_task.exception(), WorkloadResponseLost):
                raise RuntimeError("Expected response-loss fault did not occur")
            before = components.projection(session)
            await components.close()
            components = _DemoComponents(root)
            await components.start()
            # A resource report proves connectivity, not receipt reconciliation.
            # Use the existing observation-only recovery API after the original
            # persisted Node result arrives; never resubmit the mutation.
            await _wait(lambda: WORK_ID in components.server.results)
            await asyncio.to_thread(components.handler.recover_verified, WORK_ID)
            session = await components.resume(original)
            result = components.projection(session)
            result["before_recovery"] = before
            return result
        return components.projection(session)
    finally:
        await components.close()


def run_verified_demo(
    root: Path, *, scenario="match", phase="run", approval_context=None
):
    """Run one isolated local demo; human attestation remains owned by Governance."""
    if scenario not in SCENARIOS or phase not in {"run", "prepare", "resume"}:
        raise ValueError("Unsupported demo scenario or phase")
    root = root.expanduser().resolve()
    if phase != "resume" and root.exists() and any(root.iterdir()):
        raise ValueError(
            "Start requires an empty dedicated demo directory; use resume for original state"
        )
    if phase == "resume" and not (root / ".nous" / "agent_sessions.db").is_file():
        raise ValueError("No original demo session exists")
    root.mkdir(parents=True, exist_ok=True)
    with file_lock(root / ".nous" / "preview-demo.lock"):
        if phase != "resume" and (root / ".nous" / "agent_sessions.db").exists():
            raise ValueError("Original demo state already exists; use resume")
        return asyncio.run(_run(root, scenario, phase, approval_context))
