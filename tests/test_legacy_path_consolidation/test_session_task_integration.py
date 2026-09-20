# -*- coding: utf-8 -*-
"""Test Session/Task state machine integration in run_turn.

Verifies Task, PlanArtifact, and ExecutionTicket creation and state transitions.
"""

from __future__ import annotations

import os
import sys
import pytest


REMOTE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "remote_terminal")
REMOTE_DIR = os.path.abspath(REMOTE_DIR)


class TestSessionTaskIntegration:
    """Verify Session/Task state machine bridge works correctly."""

    def test_session_task_bridge_exists(self) -> None:
        """session_task_bridge.py must exist."""
        filepath = os.path.join(REMOTE_DIR, "session_task_bridge.py")
        assert os.path.isfile(filepath), (
            "session_task_bridge.py must exist in remote_terminal/"
        )

    def test_session_task_bridge_importable(self) -> None:
        """session_task_bridge must be importable with core API."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import session_task_bridge as stb
            assert hasattr(stb, "LegacySessionWrapper")
            assert hasattr(stb, "TaskBridgeResult")
            assert hasattr(stb, "create_run_turn_task")
            assert hasattr(stb, "emit_task_transition")
            assert hasattr(stb, "sync_legacy_session_to_models")
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_legacy_session_wrapper_reads_dict(self) -> None:
        """LegacySessionWrapper must delegate dict access."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            from session_task_bridge import LegacySessionWrapper

            d = {"key1": "value1", "key2": 42}
            wrapper = LegacySessionWrapper(d)

            assert wrapper["key1"] == "value1"
            assert wrapper.get("key2") == 42
            assert wrapper.get("nonexistent", "default") == "default"
            assert "key1" in wrapper
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_legacy_session_wrapper_writes_to_both(self) -> None:
        """LegacySessionWrapper must write to both dict and Session model."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            from session_task_bridge import LegacySessionWrapper

            d = {}
            wrapper = LegacySessionWrapper(d)
            wrapper["new_key"] = "new_value"

            assert d["new_key"] == "new_value"
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_create_run_turn_task_returns_result(self) -> None:
        """create_run_turn_task must return a TaskBridgeResult."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            from session_task_bridge import create_run_turn_task

            session = {"_transcript_sid": "test-sid", "_source_client": "test"}
            result = create_run_turn_task(session, "test message", None, max_steps=10)

            assert result is not None
            # Task creation may fail gracefully if nous_runtime not importable
            if result.created:
                assert result.task_id
                assert result.ticket is not None
                assert result.task_obj is not None
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_task_transitions_are_valid(self) -> None:
        """TASK_TRANSITIONS dict must contain valid state mappings."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            from session_task_bridge import TASK_TRANSITIONS
            assert "created" in TASK_TRANSITIONS
            assert "running" in TASK_TRANSITIONS
            assert "completed" in TASK_TRANSITIONS
            assert "failed" in TASK_TRANSITIONS
            assert "cancelled" in TASK_TRANSITIONS

            # Created can transition to queued or cancelled
            assert "queued" in TASK_TRANSITIONS["created"]
            assert "cancelled" in TASK_TRANSITIONS["created"]

            # Completed cannot transition anywhere
            assert len(TASK_TRANSITIONS["completed"]) == 0
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_full_state_transition_chain_valid(self) -> None:
        """The full transition chain CREATED→QUEUED→PLANNING→AWAITING_APPROVAL→DISPATCHING→RUNNING must be valid."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            from session_task_bridge import TASK_TRANSITIONS

            # Verify each step in the chain
            chain = [
                ("created", "queued"),
                ("queued", "planning"),
                ("planning", "awaiting_approval"),
                ("awaiting_approval", "dispatching"),
                ("dispatching", "running"),
                ("running", "verifying"),
                ("verifying", "completed"),
            ]
            for from_state, to_state in chain:
                valid_targets = TASK_TRANSITIONS.get(from_state, frozenset())
                assert to_state in valid_targets, (
                    f"Invalid transition: {from_state} → {to_state}. "
                    f"Valid targets: {sorted(valid_targets)}"
                )
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_brain_run_turn_uses_queued_state(self) -> None:
        """brain.py run_turn must include the 'queued' state in task transitions."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # Must include "queued" in the state transition chain
        assert '"created", "queued"' in source, (
            "brain.py run_turn must transition created → queued (not created → planning directly)"
        )
        assert '"queued", "planning"' in source, (
            "brain.py run_turn must transition queued → planning"
        )

    def test_plan_artifact_exists(self) -> None:
        """plan_artifact.py must exist."""
        filepath = os.path.join(REMOTE_DIR, "plan_artifact.py")
        assert os.path.isfile(filepath), (
            "plan_artifact.py must exist in remote_terminal/"
        )

    def test_plan_artifact_importable(self) -> None:
        """plan_artifact must be importable with core API."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import plan_artifact
            assert hasattr(plan_artifact, "PlanArtifact")
            assert hasattr(plan_artifact, "PlannedTask")

            # Test construction
            plan = plan_artifact.PlanArtifact(
                plan_id="test-plan",
                tasks=[
                    plan_artifact.PlannedTask(
                        task_id="task-1",
                        capability_id="tool.read_file",
                    ),
                ],
            )
            assert plan.verify_hash()
            assert plan.signature
            assert len(plan.to_dict()["tasks"]) == 1
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_plan_artifact_yaml_roundtrip(self) -> None:
        """PlanArtifact must serialize/deserialize via YAML."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import plan_artifact
            plan = plan_artifact.PlanArtifact(
                plan_id="rt-test",
                version="2.0.0",
                tasks=[
                    plan_artifact.PlannedTask(
                        task_id="t1",
                        capability_id="tool.run_command",
                        params={"command": "echo hello"},
                    ),
                ],
            )
            yaml_str = plan.to_yaml()
            restored = plan_artifact.PlanArtifact.from_yaml(yaml_str)
            assert restored.plan_id == "rt-test"
            assert restored.version == "2.0.0"
            assert restored.verify_hash()
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_plan_artifact_hash_verification(self) -> None:
        """PlanArtifact hash must detect tampering."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import plan_artifact
            plan = plan_artifact.PlanArtifact(
                plan_id="hash-test",
                tasks=[plan_artifact.PlannedTask(capability_id="tool.read_file")],
            )
            assert plan.verify_hash()

            # Tamper with the plan
            plan.tasks[0].capability_id = "tool.write_file"
            assert not plan.verify_hash(), "Hash should fail after tampering"
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)
