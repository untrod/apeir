# -*- coding: utf-8 -*-
"""Tests for the unified Object Model v2 (kernel/*).

Covers: NousObject, ErrorCode, NousResult, NodeIdentity, Node, Task,
        RegistryBase, StateMachine, Session, Conversation.
"""

from __future__ import annotations

import pytest

from nous_runtime.kernel.object_model import (
    Condition,
    Health,
    NousObject,
    Phase,
)
from nous_runtime.kernel.error_codes import (
    ErrorCode,
    NousResult,
    is_retryable,
    severity,
)
from nous_runtime.kernel.identity import (
    CapabilityGrant,
    NodeConnectivity,
    NodeIdentity,
    NodeRole,
    NODE_CONNECTIVITY_TRANSITIONS,
)
from nous_runtime.kernel.state_machine import (
    InvalidTransitionError,
    StateMachine,
)
from nous_runtime.kernel.registry_base import (
    RegistryBase,
)
from nous_runtime.kernel.node import (
    Node,
)
from nous_runtime.kernel.task import (
    ExecutionTicket,
    Task,
    TaskBudget,
    TaskFingerprint,
    TaskPhase,
    is_task_active,
    is_task_terminal,
)
from nous_runtime.kernel.session import (
    Conversation,
    InteractionMode,
    Message,
    Session,
)



# Error Codes


class TestErrorCode:
    def test_all_codes_are_strings(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_ok_is_ok(self):
        assert ErrorCode.OK == "OK"

    def test_retryable_codes(self):
        assert is_retryable(ErrorCode.TIMEOUT)
        assert is_retryable(ErrorCode.UNAVAILABLE)
        assert is_retryable(ErrorCode.RATE_LIMITED)
        assert is_retryable(ErrorCode.MODEL_UNAVAILABLE)
        assert is_retryable(ErrorCode.NODE_UNREACHABLE)
        assert is_retryable(ErrorCode.CONNECTION_LOST)

    def test_non_retryable_codes(self):
        assert not is_retryable(ErrorCode.OK)
        assert not is_retryable(ErrorCode.NOT_FOUND)
        assert not is_retryable(ErrorCode.PERMISSION_DENIED)
        assert not is_retryable(ErrorCode.CANCELLED)
        assert not is_retryable(ErrorCode.DATA_CORRUPTED)
        assert not is_retryable(ErrorCode.NODE_REVOKED)

    def test_severity_levels(self):
        assert severity(ErrorCode.OK) == 0
        assert severity(ErrorCode.PERMISSION_DENIED) == 2
        assert severity(ErrorCode.DATA_CORRUPTED) == 3
        assert severity(ErrorCode.NODE_REVOKED) == 3


class TestNousResult:
    def test_ok(self):
        result = NousResult.ok(42, message="all good")
        assert result.ok
        assert result.value == 42
        assert result.message == "all good"
        assert result.unwrap() == 42
        assert not result.retryable

    def test_err(self):
        result = NousResult.err(ErrorCode.TIMEOUT, message="timed out")
        assert not result.ok
        assert result.value is None
        assert result.code == ErrorCode.TIMEOUT
        assert result.retryable

    def test_unwrap_error(self):
        result = NousResult.err(ErrorCode.INTERNAL, message="boom")
        with pytest.raises(ValueError, match="boom"):
            result.unwrap()

    def test_unwrap_none_value(self):
        result = NousResult.ok(None)
        with pytest.raises(ValueError, match="no value"):
            result.unwrap()



# Object Model


class _TestCapability(NousObject):
    kind = "Capability"
    api_version = "v1"


class TestNousObject:
    def test_creation(self):
        obj = _TestCapability()
        assert obj.kind == "Capability"
        assert obj.metadata.id.startswith("cap_")
        assert obj.phase == Phase.PENDING
        assert obj.health == Health.UNKNOWN

    def test_set_phase(self):
        obj = _TestCapability()
        obj.set_phase(Phase.ACTIVE, "activated")
        assert obj.phase == Phase.ACTIVE
        assert obj.message == "activated"
        assert obj.metadata.generation == 1

    def test_is_terminal(self):
        obj = _TestCapability()
        assert not obj.is_terminal()
        obj.set_phase(Phase.COMPLETED)
        assert obj.is_terminal()
        obj2 = _TestCapability()
        obj2.set_phase(Phase.FAILED)
        assert obj2.is_terminal()

    def test_add_condition(self):
        obj = _TestCapability()
        c1 = Condition(type="Ready", status="True", reason="AllChecksPassed")
        obj.add_condition(c1)
        assert len(obj.conditions) == 1
        # Replace same type
        c2 = Condition(type="Ready", status="False", reason="Degraded")
        obj.add_condition(c2)
        assert len(obj.conditions) == 1
        assert obj.conditions[0].status == "False"

    def test_to_dict(self):
        obj = _TestCapability()
        obj.set_phase(Phase.READY)
        d = obj.to_dict()
        assert d["metadata"]["kind"] == "Capability"
        assert d["status"]["phase"] == "ready"



# State Machine


class TestStateMachine:
    def test_valid_transition(self):
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.ONLINE,
        )
        record = sm.transition(NodeConnectivity.DEGRADED, reason="High latency")
        assert sm.current == NodeConnectivity.DEGRADED
        assert record.from_state == "online"
        assert record.to_state == "degraded"
        assert record.reason == "High latency"

    def test_invalid_transition(self):
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.REVOKED,
        )
        # REVOKED → ONLINE is not allowed
        with pytest.raises(InvalidTransitionError):
            sm.transition(NodeConnectivity.ONLINE)

    def test_can_transition(self):
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.ONLINE,
        )
        assert sm.can_transition(NodeConnectivity.OFFLINE)
        assert sm.can_transition(NodeConnectivity.DEGRADED)
        assert not sm.can_transition(NodeConnectivity.RECONNECTING)

    def test_history_tracking(self):
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.ONLINE,
        )
        sm.transition(NodeConnectivity.OFFLINE, reason="Network lost")
        sm.transition(NodeConnectivity.RECONNECTING, reason="Trying...")
        assert sm.transition_count == 3  # includes initial
        assert len(sm.history) == 3

    def test_hook_called(self):
        calls = []
        def hook(record):
            calls.append(record)

        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.ONLINE,
            on_transition=hook,
        )
        sm.transition(NodeConnectivity.DEGRADED)
        assert len(calls) == 1

    def test_max_history(self):
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.ONLINE,
            max_history=3,
        )
        sm.transition(NodeConnectivity.DEGRADED)
        sm.transition(NodeConnectivity.ONLINE)
        sm.transition(NodeConnectivity.DEGRADED)
        sm.transition(NodeConnectivity.ONLINE)
        assert len(sm.history) == 3  # Capped



# Identity


class TestNodeIdentity:
    def test_creation(self):
        identity = NodeIdentity(role=NodeRole.WORKER, display_name="rtx3070")
        assert identity.node_id.startswith("node_")
        assert identity.role == NodeRole.WORKER
        assert not identity.is_revoked

    def test_revoke(self):
        identity = NodeIdentity()
        assert not identity.is_revoked
        identity.revoke()
        assert identity.is_revoked
        assert identity.revoked_at is not None


class TestCapabilityGrant:
    def test_active_grant(self):
        grant = CapabilityGrant(
            capability_id="project.read_file",
            risk_level="LOW",
        )
        assert grant.is_active
        assert not grant.is_exhausted

    def test_revoked_grant(self):
        grant = CapabilityGrant(
            capability_id="project.run_tests",
            risk_level="MEDIUM",
        )
        grant.revoked_at = "2026-01-01T00:00:00Z"
        assert not grant.is_active

    def test_exhausted_grant(self):
        grant = CapabilityGrant(
            capability_id="test.echo",
            max_invocations=3,
            invocation_count=3,
        )
        assert grant.is_exhausted


class TestNodeConnectivityTransitions:
    def test_all_defined(self):
        for state in NodeConnectivity:
            assert state in NODE_CONNECTIVITY_TRANSITIONS

    def test_revoked_is_terminal(self):
        assert len(NODE_CONNECTIVITY_TRANSITIONS[NodeConnectivity.REVOKED]) == 0

    def test_online_can_go_offline(self):
        assert NodeConnectivity.OFFLINE in NODE_CONNECTIVITY_TRANSITIONS[NodeConnectivity.ONLINE]

    def test_online_can_be_revoked(self):
        assert NodeConnectivity.REVOKED in NODE_CONNECTIVITY_TRANSITIONS[NodeConnectivity.ONLINE]



# Node


class TestNode:
    def test_creation(self):
        node = Node()
        assert node.kind == "Node"
        assert node.metadata.id.startswith("node_")
        assert node.connectivity == NodeConnectivity.OFFLINE
        assert node.role == NodeRole.WORKER

    def test_connectivity_lifecycle(self):
        node = Node()
        node.mark_online(reason="Boot complete")
        assert node.is_online
        assert node.connectivity == NodeConnectivity.ONLINE

        node.mark_degraded(reason="GPU throttled")
        assert node.is_online  # still online
        assert node.connectivity == NodeConnectivity.DEGRADED

        node.mark_offline(reason="Network lost")
        assert not node.is_online

    def test_revoke(self):
        node = Node()
        node.mark_online()
        node.mark_revoked(reason="Security breach")
        assert node.is_revoked
        assert node.identity.is_revoked

    def test_heartbeat(self):
        node = Node()
        node.mark_online()
        node.heartbeat_interval_ms = 30000
        node.record_heartbeat()
        assert node.last_heartbeat != ""
        assert node.heartbeat_missed_ms < 1000  # just recorded
        assert not node.heartbeat_timed_out

    def test_heartbeat_timeout(self):
        node = Node()
        node.mark_online()
        node.heartbeat_interval_ms = 1  # 1ms interval
        node.last_heartbeat = "2020-01-01T00:00:00Z"
        assert node.heartbeat_timed_out

    def test_active_grants(self):
        node = Node()
        grant = CapabilityGrant(
            capability_id="project.read_file",
            risk_level="LOW",
        )
        node.grants.append(grant)
        assert len(node.active_grants) == 1
        grant.revoked_at = "2026-01-01T00:00:00Z"
        assert len(node.active_grants) == 0

    def test_to_dict(self):
        node = Node()
        node.mark_online()
        d = node.to_dict()
        assert d["node"]["connectivity"] == "online"
        assert "identity" in d["node"]



# Task


class TestTask:
    def test_creation(self):
        task = Task(objective="Run tests for nous_runtime")
        assert task.kind == "Task"
        assert task.phase == TaskPhase.CREATED
        assert task.objective == "Run tests for nous_runtime"
        assert task.is_active
        assert not task.is_terminal

    def test_full_lifecycle_happy_path(self):
        task = Task(objective="Fix bug in auth.py")
        # CREATED → QUEUED
        task.transition(TaskPhase.QUEUED, reason="Scheduler picked up")
        assert task.phase == TaskPhase.QUEUED

        # QUEUED → PLANNING
        task.transition(TaskPhase.PLANNING, reason="Planner assigned")
        assert task.phase == TaskPhase.PLANNING

        # PLANNING → AWAITING_APPROVAL
        task.transition(TaskPhase.AWAITING_APPROVAL, reason="Plan ready for review")
        assert task.phase == TaskPhase.AWAITING_APPROVAL

        # AWAITING_APPROVAL → DISPATCHING
        task.transition(TaskPhase.DISPATCHING, reason="User approved")
        assert task.phase == TaskPhase.DISPATCHING

        # DISPATCHING → RUNNING
        task.transition(TaskPhase.RUNNING, reason="Dispatched to worker")
        assert task.phase == TaskPhase.RUNNING

        # RUNNING → VERIFYING
        task.transition(TaskPhase.VERIFYING, reason="Execution done, verifying")
        assert task.phase == TaskPhase.VERIFYING

        # VERIFYING → COMPLETED
        task.transition(TaskPhase.COMPLETED, reason="Verification passed")
        assert task.phase == TaskPhase.COMPLETED
        assert task.is_terminal

    def test_can_cancel_at_any_active_state(self):
        # Most active states allow cancellation
        task = Task()
        task.transition(TaskPhase.QUEUED)
        task.transition(TaskPhase.CANCELLED, reason="User cancelled")
        assert task.phase == TaskPhase.CANCELLED
        assert task.is_terminal

    def test_cannot_transition_from_terminal(self):
        task = Task()
        task.transition(TaskPhase.CANCELLED)
        with pytest.raises(InvalidTransitionError):
            task.transition(TaskPhase.RUNNING)

    def test_waiting_for_node_recovery(self):
        task = Task()
        task.transition(TaskPhase.QUEUED)
        task.transition(TaskPhase.PLANNING)
        task.transition(TaskPhase.AWAITING_APPROVAL)
        task.transition(TaskPhase.DISPATCHING)
        task.transition(TaskPhase.WAITING_FOR_NODE, reason="Worker offline")
        assert task.phase == TaskPhase.WAITING_FOR_NODE

        # Can recover
        task.transition(TaskPhase.RECOVERING, reason="Worker back online")
        assert task.phase == TaskPhase.RECOVERING
        task.transition(TaskPhase.DISPATCHING, reason="Re-dispatched")
        assert task.phase == TaskPhase.DISPATCHING

    def test_pause_and_resume(self):
        task = Task()
        task.transition(TaskPhase.QUEUED)
        task.transition(TaskPhase.PLANNING)
        task.transition(TaskPhase.AWAITING_APPROVAL)
        task.transition(TaskPhase.DISPATCHING)
        task.transition(TaskPhase.RUNNING)
        task.transition(TaskPhase.PAUSED, reason="User paused")
        assert task.phase == TaskPhase.PAUSED
        task.transition(TaskPhase.RUNNING, reason="User resumed")
        assert task.phase == TaskPhase.RUNNING

    def test_checkpoint(self):
        task = Task(objective="Long task")
        task.current_step = 42
        ckpt = task.create_checkpoint(node_id="worker-1")
        assert ckpt.object_id == task.metadata.id
        assert ckpt.state_snapshot["current_step"] == 42
        assert len(task.checkpoints) == 1

    def test_restore_from_checkpoint(self):
        task = Task()
        task.transition(TaskPhase.QUEUED)
        task.transition(TaskPhase.PLANNING)
        task.transition(TaskPhase.AWAITING_APPROVAL)
        task.transition(TaskPhase.DISPATCHING)
        task.transition(TaskPhase.RUNNING)
        task.current_step = 5

        ckpt = task.create_checkpoint()

        # Simulate failure
        task2 = Task(objective="Restored task")
        task2.restore_from_checkpoint(ckpt)
        assert task2.phase == TaskPhase.RUNNING
        assert task2.current_step == 5

    def test_budget_tracking(self):
        budget = TaskBudget(max_tokens=10000, max_cost_cents=500)
        budget.tokens_spent = 10000
        assert budget.tokens_exceeded
        assert not budget.cost_exceeded
        assert budget.any_budget_exceeded

    def test_budget_unlimited(self):
        budget = TaskBudget()  # All zeros = unlimited
        budget.tokens_spent = 999999
        assert not budget.tokens_exceeded
        assert not budget.any_budget_exceeded

    def test_task_fingerprint(self):
        fp = TaskFingerprint(
            task_type="code_fix",
            required_capabilities=["project.read_file", "project.run_tests"],
            privacy_level="standard",
            risk_level="MEDIUM",
            requires_approval=True,
            requires_verification=True,
        )
        d = fp.to_dict()
        assert d["task_type"] == "code_fix"
        assert len(d["required_capabilities"]) == 2

    def test_execution_ticket(self):
        ticket = ExecutionTicket(
            plan_id="plan-001",
            task_id="task-001",
            approved_by="user-001",
            target_node_id="worker-1",
            step_count=5,
        )
        assert ticket.ticket_id.startswith("ticket_")
        assert not ticket.is_expired  # No expiry set

    def test_terminal_states(self):
        for phase in (TaskPhase.COMPLETED, TaskPhase.COMPLETED_WITH_WARNINGS,
                       TaskPhase.FAILED, TaskPhase.FAILED_VERIFICATION,
                       TaskPhase.CANCELLED):
            assert is_task_terminal(phase)
            assert not is_task_active(phase)

    def test_active_states(self):
        for phase in (TaskPhase.CREATED, TaskPhase.QUEUED, TaskPhase.PLANNING,
                       TaskPhase.AWAITING_APPROVAL, TaskPhase.DISPATCHING,
                       TaskPhase.RUNNING, TaskPhase.VERIFYING, TaskPhase.RECOVERING):
            assert is_task_active(phase)
            assert not is_task_terminal(phase)



# Registry Base


class _TestNodeRegistry(RegistryBase[Node]):
    object_kind = "Node"
    object_type = Node


class _TestTaskRegistry(RegistryBase[Task]):
    object_kind = "Task"
    object_type = Task


class TestRegistryBase:
    def test_register_and_get(self):
        reg = _TestNodeRegistry()
        node = Node()
        result = reg.register(node)
        assert result.ok

        result2 = reg.get(node.metadata.id)
        assert result2.ok
        assert result2.value.metadata.id == node.metadata.id

    def test_register_duplicate(self):
        reg = _TestNodeRegistry()
        node = Node()
        reg.register(node)
        result = reg.register(node)
        assert not result.ok
        assert result.code == ErrorCode.ALREADY_EXISTS

    def test_unregister(self):
        reg = _TestNodeRegistry()
        node = Node()
        reg.register(node)
        assert reg.count() == 1

        reg.unregister(node.metadata.id)
        assert reg.count() == 0

    def test_unregister_missing(self):
        reg = _TestNodeRegistry()
        result = reg.unregister("nonexistent")
        assert not result.ok
        assert result.code == ErrorCode.NOT_FOUND

    def test_list(self):
        reg = _TestNodeRegistry()
        n1 = Node()
        n2 = Node()
        reg.register(n1)
        reg.register(n2)
        result = reg.list()
        assert result.ok
        assert len(result.value) == 2

    def test_list_with_filter(self):
        reg = _TestNodeRegistry()
        n1 = Node()
        n1.mark_online()
        n2 = Node()  # stays OFFLINE
        reg.register(n1)
        reg.register(n2)

        online = reg.list(filter_fn=lambda n: n.is_online)
        assert online.ok
        assert len(online.value) == 1

    def test_update(self):
        reg = _TestNodeRegistry()
        node = Node()
        reg.register(node)

        def rename(n):
            n.identity.display_name = "renamed-node"
            return n

        result = reg.update(node.metadata.id, rename)
        assert result.ok
        assert result.value.identity.display_name == "renamed-node"

    def test_health_aggregation(self):
        reg = _TestNodeRegistry()
        n1 = Node()
        n2 = Node()
        reg.register(n1)
        reg.register(n2)

        h = reg.health()
        assert h.ok
        assert h.value["count"] == 2
        assert h.value["health"] in ("unknown", "ok", "degraded", "down")

    def test_thread_safety(self):
        import threading
        reg = _TestNodeRegistry()
        errors = []

        def register_nodes(start, count):
            for i in range(start, start + count):
                node = Node()
                result = reg.register(node)
                if not result.ok:
                    errors.append(result.message)

        threads = [
            threading.Thread(target=register_nodes, args=(i * 100, 50))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert reg.count() == 200

    def test_audit_events(self):
        reg = _TestNodeRegistry()
        node = Node()
        reg.register(node)
        reg.unregister(node.metadata.id)

        events = reg.get_events()
        assert len(events) >= 2

    def test_clear(self):
        reg = _TestNodeRegistry()
        reg.register(Node())
        reg.register(Node())
        reg.clear()
        assert reg.count() == 0



# Session & Conversation


class TestMessage:
    def test_creation(self):
        msg = Message(role="user", content="Hello")
        assert msg.message_id.startswith("msg_")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_to_dict(self):
        msg = Message(role="assistant", content="Hi!", task_id="task-1")
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["task_id"] == "task-1"


class TestConversation:
    def test_creation(self):
        conv = Conversation(user_id="user-1", title="Test Chat")
        assert conv.kind == "Conversation"
        assert conv.mode == InteractionMode.DISCUSS
        assert conv.message_count == 0

    def test_add_message(self):
        conv = Conversation(user_id="user-1")
        msg = Message(role="user", content="Run tests")
        conv.add_message(msg)
        assert conv.message_count == 1
        assert len(conv.messages) == 1

    def test_add_task(self):
        conv = Conversation(user_id="user-1")
        conv.add_task("task-001")
        conv.add_task("task-002")
        conv.add_task("task-001")  # dedup
        assert len(conv.task_ids) == 2

    def test_recent_messages(self):
        conv = Conversation(user_id="user-1")
        for i in range(30):
            conv.add_message(Message(role="user", content=f"msg {i}"))
        assert len(conv.recent_messages(10)) == 10

    def test_to_dict(self):
        conv = Conversation(user_id="user-1", title="Dev Chat")
        conv.add_message(Message(role="user", content="hello"))
        d = conv.to_dict()
        assert d["conversation"]["title"] == "Dev Chat"
        assert d["conversation"]["message_count"] == 1


class TestSession:
    def test_creation(self):
        session = Session(user_id="user-1")
        assert session.kind == "Session"
        assert not session.is_expired

    def test_expiry(self):
        session = Session(user_id="user-1", ttl_seconds=1)
        session.last_active_at = "2020-01-01T00:00:00Z"
        assert session.is_expired

    def test_touch(self):
        session = Session(user_id="user-1", ttl_seconds=86400)
        session.last_active_at = "2020-01-01T00:00:00Z"
        session.touch()
        assert not session.is_expired  # Just touched
