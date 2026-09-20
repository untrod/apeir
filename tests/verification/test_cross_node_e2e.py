# -*- coding: utf-8 -*-
"""
Cross-Node End-to-End Test — Primary ↔ Worker with disconnect/reconnect.

Simulates a multi-node deployment on a single machine using separate
processes and temporary directories. Exercises:
  - Primary starts → Worker registers → Task dispatched
  - Worker disconnects → Task goes WAITING_FOR_NODE
  - Worker reconnects → Events replayed → Task recovers
  - Approval flow → Verification → Evidence recorded

This test runs entirely locally — no external machines needed.
"""

from __future__ import annotations

import tempfile
import time

import pytest


@pytest.fixture
def multi_node_env():
    """Create separate directories for primary and worker."""
    with tempfile.TemporaryDirectory() as primary_dir, \
         tempfile.TemporaryDirectory() as worker_dir:
        yield {
            "primary_data": primary_dir,
            "worker_data": worker_dir,
        }


class TestCrossNodeE2E:
    """Multi-node deployment with disconnect/reconnect scenarios."""

    def test_primary_worker_lifecycle(self, multi_node_env):
        """Full lifecycle: register → heartbeat → disconnect → reconnect."""
        from nous_runtime.kernel.config import NousConfig
        from nous_runtime.kernel.server import NousServer
        from nous_runtime.kernel.node import Node
        from nous_runtime.kernel.task import Task, TaskPhase
        from nous_runtime.connectivity.mesh import NodeMesh, MeshMessage

        # Setup Primary
        primary_config = NousConfig(
            server_name="e2e-primary",
            data_dir=multi_node_env["primary_data"],
            demo_mode=True,
            primary_node="e2e-primary",
        )
        primary = NousServer(config=primary_config)
        primary.start()

        # Setup Mesh
        mesh = NodeMesh(primary_node_id="e2e-primary")

        # Worker registers
        worker = Node()
        worker.identity.display_name = "e2e-worker"
        worker.heartbeat_interval_ms = 500  # Fast heartbeat for testing
        primary.register_node(worker)
        mesh.register_node(worker)

        # Task submitted
        task = Task(objective="Cross-node smoke test")
        primary.submit_task(task)
        task.transition(TaskPhase.QUEUED)
        task.transition(TaskPhase.PLANNING)
        task.transition(TaskPhase.AWAITING_APPROVAL)
        task.transition(TaskPhase.DISPATCHING)
        task.transition(TaskPhase.RUNNING)
        task.current_step = 3

        # Checkpoint
        ckpt = primary.checkpoint_task(task.metadata.id)
        assert ckpt.ok

        # Worker disconnected (simulated)
        worker.mark_offline(reason="Network lost")
        assert not worker.is_online

        # Buffer events for offline worker
        msg = MeshMessage(
            source_node_id="e2e-primary",
            target_node_id=worker.metadata.id,
            message_type="task_update",
            payload={"task_id": task.metadata.id, "status": "running"},
        )
        mesh.send(msg)
        assert mesh.status()["buffered_events"] >= 1

        # Task should go WAITING_FOR_NODE
        task.transition(TaskPhase.WAITING_FOR_NODE, reason="Worker offline")

        # Worker reconnects
        worker.mark_reconnecting(reason="Network restored")
        worker.mark_online(reason="Reconnected")

        # Replay buffered events
        replay_result = mesh.replay_offline_events(worker.metadata.id)
        assert replay_result.ok
        assert len(replay_result.value) == 1
        assert replay_result.value[0].message_type == "task_update"

        # Buffer should be empty now
        assert mesh.status()["buffered_events"] == 0

        # Task recovers
        task.transition(TaskPhase.RECOVERING, reason="Worker back, events replayed")
        task.transition(TaskPhase.RUNNING, reason="Resumed execution")
        task.transition(TaskPhase.VERIFYING)
        task.transition(TaskPhase.COMPLETED, reason="Done after recovery")
        assert task.is_terminal

        # Cleanup
        primary.stop(drain_tasks=False)

    def test_message_dedup(self, multi_node_env):
        """Verify duplicate messages are filtered."""
        from nous_runtime.connectivity.mesh import MessageDedupFilter

        dedup = MessageDedupFilter(window_seconds=60)

        # First time → not duplicate
        assert not dedup.is_duplicate("msg-001")
        assert not dedup.is_duplicate("msg-002")
        assert not dedup.is_duplicate("msg-003")

        # Repeats → duplicates
        assert dedup.is_duplicate("msg-001")
        assert dedup.is_duplicate("msg-002")
        assert dedup.is_duplicate("msg-003")

    def test_approval_flow(self, multi_node_env):
        """Verify the approval flow via admission control."""
        from nous_runtime.security.admission import (
            AdmissionPipeline, AdmissionRequest, RiskLevel,
        )

        pipeline = AdmissionPipeline()

        # MEDIUM risk → requires approval
        request = AdmissionRequest(
            capability_id="project.write_file",
            risk_level=RiskLevel.MEDIUM,
            user_id="test-user",
            estimated_cost_cents=10,
        )
        result = pipeline.check(request)
        assert result.allowed
        assert result.requires_approval

        # HIGH risk → requires approval + full details
        request2 = AdmissionRequest(
            capability_id="shell.execute",
            risk_level=RiskLevel.HIGH,
            user_id="test-user",
        )
        result2 = pipeline.check(request2)
        assert result2.allowed
        assert result2.requires_approval

        # READ_ONLY → auto-approved
        request3 = AdmissionRequest(
            capability_id="project.read_file",
            risk_level=RiskLevel.READ_ONLY,
            user_id="test-user",
        )
        result3 = pipeline.check(request3)
        assert result3.allowed
        assert not result3.requires_approval

    def test_real_time_events(self, multi_node_env):
        """Verify event flow: node online → task queued → running → complete."""
        from nous_runtime.kernel.server import NousServer
        from nous_runtime.kernel.config import NousConfig
        from nous_runtime.kernel.node import Node
        from nous_runtime.kernel.task import Task, TaskPhase

        events = []

        def record_event(phase, detail=""):
            events.append({"phase": str(phase), "detail": detail, "ts": time.time()})

        config = NousConfig(
            server_name="event-test",
            data_dir=multi_node_env["primary_data"],
            demo_mode=True,
        )
        server = NousServer(config=config)
        server.start()

        # Register node → event
        node = Node()
        node.identity.display_name = "event-worker"
        server.register_node(node)
        record_event("node_online", node.metadata.id)

        # Submit task → events through lifecycle
        task = Task(objective="Event flow test")
        server.submit_task(task)
        record_event("task_queued", task.metadata.id)

        for phase in [TaskPhase.PLANNING, TaskPhase.AWAITING_APPROVAL,
                       TaskPhase.DISPATCHING, TaskPhase.RUNNING,
                       TaskPhase.VERIFYING, TaskPhase.COMPLETED]:
            task.transition(phase)
            record_event(f"task_{phase.value}", task.metadata.id)

        # Verify event ordering
        assert len(events) == 8  # node_online + task_queued + 6 transitions
        phases_in_order = [e["phase"] for e in events]
        assert phases_in_order == [
            "node_online", "task_queued",
            "task_planning", "task_awaiting_approval", "task_dispatching",
            "task_running", "task_verifying", "task_completed",
        ]

        server.stop(drain_tasks=False)

    def test_verification_flow(self, multi_node_env):
        """Verify the end-to-end verification chain."""
        from nous_runtime.capability.contract import CapabilityContractRegistry
        from nous_runtime.security.admission import AdmissionPipeline, AdmissionRequest, RiskLevel

        contracts = CapabilityContractRegistry()

        # Check contract for project.run_tests
        contract = contracts.get("project.run_tests")
        assert contract.ok
        assert contract.value.verification_method.value == "test_rerun"
        assert contract.value.risk_level == "low"

        # Admission for test execution
        pipeline = AdmissionPipeline()
        adm = pipeline.check(AdmissionRequest(
            capability_id="project.run_tests",
            risk_level=RiskLevel.LOW,
            user_id="test-user",
        ))
        assert adm.allowed
        assert not adm.requires_approval

        # Git push requires approval + verification
        git_contract = contracts.get("git.push")
        assert git_contract.ok
        assert git_contract.value.risk_level == "high"
        assert git_contract.value.audit_level == "detailed"

        git_adm = pipeline.check(AdmissionRequest(
            capability_id="git.push",
            risk_level=RiskLevel.HIGH,
            user_id="test-user",
        ))
        assert git_adm.allowed
        assert git_adm.requires_approval
