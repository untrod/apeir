# -*- coding: utf-8 -*-
"""Verify all kernel public exports are importable and have correct types."""

from __future__ import annotations

from nous_runtime.kernel.task import is_task_terminal



def test_kernel_init_exports_all_symbols():
    """Ensure kernel.__init__ exports everything that submodules define."""
    from nous_runtime.kernel import __all__ as kernel_all
    assert "NousObject" in kernel_all
    assert "ErrorCode" in kernel_all
    assert "NousResult" in kernel_all
    assert "Node" in kernel_all
    assert "Task" in kernel_all
    assert "TaskPhase" in kernel_all
    assert "RegistryBase" in kernel_all
    assert "StateMachine" in kernel_all
    assert "Checkpoint" in kernel_all
    assert "Lease" in kernel_all
    assert "NodeConnectivity" in kernel_all
    assert "NodeIdentity" in kernel_all
    assert "CapabilityGrant" in kernel_all
    assert "Session" not in kernel_all  # Currently not exported from kernel
    assert "Conversation" not in kernel_all


def test_nous_object_imports():
    from nous_runtime.kernel.object_model import (
        Condition, Health, NousObject,
    )
    assert Condition is not None
    assert Health is not None
    assert NousObject is not None


def test_error_codes_imports():
    from nous_runtime.kernel.error_codes import ErrorCode, NousResult, is_retryable
    assert ErrorCode.OK == "OK"
    api_result = NousResult.ok(42)
    assert api_result.ok
    assert is_retryable(ErrorCode.TIMEOUT)


def test_identity_imports():
    from nous_runtime.kernel.identity import (
        NodeIdentity, NodeRole, NodeConnectivity,
    )
    identity = NodeIdentity(role=NodeRole.PRIMARY)
    assert identity.node_id.startswith("node_")
    assert NodeConnectivity.ONLINE.value == "online"


def test_state_machine_imports():
    from nous_runtime.kernel.state_machine import (
        StateMachine, Checkpoint, Lease,
    )
    assert StateMachine is not None
    assert Checkpoint is not None
    assert Lease is not None


def test_node_imports():
    from nous_runtime.kernel.node import Node
    node = Node()
    assert node.kind == "Node"
    assert node.connectivity.value == "offline"


def test_task_imports():
    from nous_runtime.kernel.task import Task, TaskPhase
    task = Task(objective="Test")
    assert task.phase == TaskPhase.CREATED
    assert is_task_terminal(TaskPhase.COMPLETED)
    assert not is_task_terminal(TaskPhase.RUNNING)


def test_registry_base_imports():
    from nous_runtime.kernel.registry_base import RegistryBase
    assert RegistryBase is not None


def test_session_imports():
    from nous_runtime.kernel.session import Conversation, Session
    conv = Conversation(user_id="u1")
    assert conv.kind == "Conversation"
    session = Session(user_id="u1")
    assert session.kind == "Session"
