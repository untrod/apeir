# -*- coding: utf-8 -*-
"""Traceability tests — task → decision → outcome → audit linkage."""

import time


def test_decision_outcome_linkage(control_plane):
    """Task execution produces decision + outcome records."""
    from nous_runtime.connectivity.node.daemon import NodeDaemon
    from nous_runtime.connectivity.protocol.identity import NodeIdentity
    from nous_runtime.connectivity.control_plane.linkage import (
        get_task_decision,
        get_task_outcome,
        verify_linkage,
    )
    import platform
    import secrets

    cp = control_plane

    # Pair and connect a node
    code = cp.pairing.create_code()
    pk = secrets.token_hex(32)
    identity = NodeIdentity.create(
        node_name="trace-node",
        node_role="personal_node",
        platform_os=platform.system(),
        platform_os_version=platform.release(),
        platform_arch=platform.machine(),
        platform_hostname=platform.node(),
        public_key=pk,
        capabilities=["system.echo"],
    )
    node = NodeDaemon(
        control_plane_host=cp.host,
        control_plane_port=cp.port,
        node_name="trace-node",
    )
    assert node.pair(code, identity)
    node.start()
    from tests.test_connectivity.test_vertical_slice import _wait_for_welcome

    try:
        _wait_for_welcome(node, cp)

        # Submit task
        task = cp.submit_task("system.echo", {"message": "traceability"})
        assert task is not None
        task_id = task["task_id"]

        # Wait for execution
        deadline = time.monotonic() + 1.5
        while get_task_outcome(task_id) is None and time.monotonic() < deadline:
            time.sleep(0.01)

        # Verify decision record exists
        decision = get_task_decision(task_id)
        assert decision is not None, f"No decision record for task {task_id}"
        assert decision["task_id"] == task_id
        assert decision["decision_type"] == "task_routing"
        assert decision["selected_node"] == identity.node_id
        print(f"  Decision: {decision['decision_id']}")

        # Verify outcome record exists
        outcome = get_task_outcome(task_id)
        assert outcome is not None, f"No outcome record for task {task_id}"
        assert outcome["task_id"] == task_id
        assert outcome["decision_id"] == decision["decision_id"]
        print(
            f"  Outcome: {outcome['outcome_id']} linked to decision {outcome['decision_id']}"
        )

        # Verify full linkage
        linkage = verify_linkage(task_id)
        assert linkage["has_decision"], "Missing decision"
        assert linkage["has_outcome"], "Missing outcome"
        assert linkage["decision_outcome_linked"], "Decision and outcome not linked"
        print(f"  Linkage verified: {linkage}")

    finally:
        node.stop()


def test_no_false_decision_no_routing(control_plane):
    """When no scheduling decision occurs, only direct routing reason is recorded."""
    from nous_runtime.connectivity.control_plane.task_coordinator import TaskCoordinator
    from nous_runtime.connectivity.control_plane.linkage import get_task_decision
    from nous_runtime.connectivity.protocol.task import TaskSubmission

    # Submit a task directly (no routing needed)
    sub = TaskSubmission.create("system.echo", {"message": "direct"})
    tc = TaskCoordinator()
    success, msg, task = tc.submit(sub)
    assert success

    # No decision yet — task is only QUEUED, not assigned
    decision = get_task_decision(sub.task_id)
    # Decision only created on assignment, not on submission
    if decision is not None:
        assert decision.get("reason") == "deterministic_routing"


def test_missing_outcome_still_fails_and_stops_node(control_plane, monkeypatch):
    """Waiting for a real record cannot manufacture success or leak its Node."""
    import pytest

    from nous_runtime.connectivity.control_plane import linkage
    from nous_runtime.connectivity.node.daemon import NodeDaemon

    stopped = []
    original_stop = NodeDaemon.stop

    def observed_stop(node):
        original_stop(node)
        stopped.append(node)

    monkeypatch.setattr(linkage, "get_task_outcome", lambda *_: None)
    monkeypatch.setattr(NodeDaemon, "stop", observed_stop)
    with pytest.raises(AssertionError, match="No outcome record"):
        test_decision_outcome_linkage(control_plane)
    assert len(stopped) == 1
    assert not stopped[0].is_connected()
    assert not stopped[0]._thread.is_alive()
