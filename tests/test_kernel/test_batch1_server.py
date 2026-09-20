# -*- coding: utf-8 -*-
"""Tests for Batch 1 — Server Primary components.

Covers: CheckpointStore, NousConfig, NousServer health, crash recovery.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from nous_runtime.kernel.config import NousConfig, get_config
from nous_runtime.kernel.checkpoint_store import CheckpointStore
from nous_runtime.kernel.state_machine import Checkpoint
from nous_runtime.kernel.node import Node
from nous_runtime.kernel.task import Task, TaskPhase
from nous_runtime.kernel.error_codes import ErrorCode


@pytest.fixture(name="server_config")
def shared_server_config(tmp_path):
    """Reusable server config for server and integration test classes."""
    return NousConfig(server_name="test-server", data_dir=str(tmp_path), demo_mode=True)



# Checkpoint Store


class TestCheckpointStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_checkpoints.db")
            yield CheckpointStore(db_path)

    def test_save_and_load(self, store):
        ckpt = Checkpoint(
            object_id="task-001",
            object_kind="Task",
            node_id="node-1",
            sequence_number=0,
            state_snapshot={"phase": "running", "step": 3},
        )
        result = store.save(ckpt)
        assert result.ok

        loaded = store.load(ckpt.checkpoint_id)
        assert loaded.ok
        assert loaded.value.object_id == "task-001"
        assert loaded.value.state_snapshot["phase"] == "running"
        assert loaded.value.state_snapshot["step"] == 3

    def test_load_latest(self, store):
        ckpt1 = Checkpoint(
            object_id="task-001", object_kind="Task",
            sequence_number=0, state_snapshot={"phase": "planning"},
        )
        ckpt2 = Checkpoint(
            object_id="task-001", object_kind="Task",
            sequence_number=1, state_snapshot={"phase": "running"},
        )
        store.save(ckpt1)
        store.save(ckpt2)

        latest = store.load_latest("task-001")
        assert latest.ok
        assert latest.value.sequence_number == 1
        assert latest.value.state_snapshot["phase"] == "running"

    def test_load_nonexistent(self, store):
        result = store.load("nonexistent")
        assert not result.ok
        assert result.code == ErrorCode.NOT_FOUND

    def test_list_for_object(self, store):
        for i in range(5):
            ckpt = Checkpoint(
                object_id="task-002", object_kind="Task",
                sequence_number=i, state_snapshot={"step": i},
            )
            store.save(ckpt)

        result = store.list_for_object("task-002", limit=3)
        assert result.ok
        assert len(result.value) == 3
        # Newest first
        assert result.value[0].sequence_number == 4

    def test_find_recoverable(self, store):
        # Save a task in "running" state (should be recoverable)
        ckpt_active = Checkpoint(
            object_id="task-active", object_kind="Task",
            sequence_number=0, state_snapshot={"phase": "running"},
        )
        store.save(ckpt_active)

        # Save a task in "completed" state (should NOT be recoverable)
        ckpt_done = Checkpoint(
            object_id="task-done", object_kind="Task",
            sequence_number=0, state_snapshot={"phase": "completed"},
        )
        store.save(ckpt_done)

        result = store.find_recoverable("Task")
        assert result.ok
        recoverable_ids = [c.object_id for c in result.value]
        assert "task-active" in recoverable_ids
        assert "task-done" not in recoverable_ids

    def test_find_recoverable_filters_failed_verification(self, store):
        ckpt = Checkpoint(
            object_id="task-fail", object_kind="Task",
            sequence_number=0, state_snapshot={"phase": "failed_verification"},
        )
        store.save(ckpt)

        result = store.find_recoverable("Task")
        assert result.ok
        # failed_verification IS terminal — should NOT appear
        recoverable_ids = [c.object_id for c in result.value]
        assert "task-fail" not in recoverable_ids

    def test_prune(self, store):
        # Save 10 checkpoints for same object
        for i in range(10):
            ckpt = Checkpoint(
                object_id="task-prune", object_kind="Task",
                sequence_number=i, state_snapshot={"step": i},
            )
            store.save(ckpt)

        assert store.count() == 10

        # Keep only 3 most recent
        result = store.prune(max_per_object=3)
        assert result.ok
        assert store.count() == 3

        # Verify only the latest 3 remain
        remaining = store.list_for_object("task-prune")
        assert len(remaining.value) == 3
        seqs = [c.sequence_number for c in remaining.value]
        assert seqs == [9, 8, 7]



# NousConfig


class TestNousConfig:
    def test_load_defaults(self):
        config = NousConfig.load(project_root=tempfile.mkdtemp())
        assert config.server_port == 8770
        assert config.server_name == "nous-primary"
        assert config.llm_model == "deepseek-chat"
        assert config.llm_timeout == 60
        assert config.safety_mode == "normal"
        assert config.fallback_policy == "cloud_or_wait"

    def test_to_dict_hides_secrets(self):
        config = NousConfig(
            llm_api_key="sk-secret-123",
        auth_token="token-secret",  # security-scan: fixture
        )
        d = config.to_dict(hide_secrets=True)
        # Secrets should not appear
        assert "auth_token" not in str(d)
        provider = d.get("provider", {})
        assert provider.get("llm_model") == "deepseek-chat"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NOUS_BRAIN_PORT", "9999")
        monkeypatch.setenv("NOUS_LLM_MODEL", "gpt-4")
        config = NousConfig.load(project_root=tempfile.mkdtemp())
        assert config.server_port == 9999
        assert config.llm_model == "gpt-4"

    def test_preferred_workers_parsing(self, monkeypatch):
        monkeypatch.setenv("NOUS_PREFERRED_WORKERS", "rtx3070,rtx4080,jetson")
        config = NousConfig.load(project_root=tempfile.mkdtemp())
        assert len(config.preferred_workers) == 3
        assert "rtx3070" in config.preferred_workers

    def test_get_config_singleton(self, monkeypatch):
        monkeypatch.setenv("NOUS_SERVER_NAME", "test-primary")
        config = get_config()
        assert config.server_name == "test-primary"
        # Second call returns same instance
        config2 = get_config()
        assert config2 is config



# NousServer (lightweight — no HTTP)


class TestNousServer:
    @pytest.fixture
    def server_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield NousConfig(
                server_name="test-server",
                data_dir=tmp,
                demo_mode=True,
            )

    def test_server_start_stop(self, server_config):
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            health = server.start()
            assert health.status in ("running", "degraded")
            assert server.is_running()
        finally:
            server.stop(drain_tasks=False)

        assert not server.is_running()

    def test_server_health(self, server_config):
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            server.start()
            health = server.health()
            assert health.status in ("running", "degraded")
            assert health.version != ""
            d = health.to_dict()
            assert "nodes" in d
            assert "tasks" in d
            assert "checkpoints" in d
        finally:
            server.stop(drain_tasks=False)

    def test_register_and_heartbeat_node(self, server_config):
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            server.start()
            node = Node()
            result = server.register_node(node)
            assert result.ok
            assert node.is_online

            # Heartbeat
            node.last_heartbeat = "2020-01-01T00:00:00Z"  # force timeout
            # Wait for heartbeat monitor...
            result2 = server.node_heartbeat(node.metadata.id)
            assert result2.ok
            assert node.is_online  # Back online after heartbeat
        finally:
            server.stop(drain_tasks=False)

    def test_submit_and_cancel_task(self, server_config):
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            server.start()
            task = Task(objective="Test task")
            result = server.submit_task(task)
            assert result.ok
            assert task.phase == TaskPhase.QUEUED

            result2 = server.cancel_task(task.metadata.id, reason="No longer needed")
            assert result2.ok
            assert result2.value.phase == TaskPhase.CANCELLED
        finally:
            server.stop(drain_tasks=False)

    def test_checkpoint_task(self, server_config):
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            server.start()

            task = Task(objective="Long running task")
            task.transition(TaskPhase.QUEUED)
            task.transition(TaskPhase.PLANNING)
            task.transition(TaskPhase.AWAITING_APPROVAL)
            task.transition(TaskPhase.DISPATCHING)
            task.transition(TaskPhase.RUNNING)
            server.task_registry.register(task)

            result = server.checkpoint_task(task.metadata.id)
            assert result.ok

            # Load back
            loaded = server._checkpoint_store.load(result.value.checkpoint_id)
            assert loaded.ok
            assert loaded.value.state_snapshot["phase"] == "running"
        finally:
            server.stop(drain_tasks=False)

    def test_recover_tasks_after_restart(self, server_config):
        from nous_runtime.kernel.server import NousServer

        # First server instance — create a running task
        server1 = NousServer(config=server_config)
        try:
            server1.start()

            task = Task(objective="Survive restart")
            task.transition(TaskPhase.QUEUED)
            task.transition(TaskPhase.PLANNING)
            task.transition(TaskPhase.AWAITING_APPROVAL)
            task.transition(TaskPhase.DISPATCHING)
            task.transition(TaskPhase.RUNNING)
            task.current_step = 7
            server1.task_registry.register(task)

            # Checkpoint it
            ckpt_result = server1.checkpoint_task(task.metadata.id)
            assert ckpt_result.ok
        finally:
            server1.stop(drain_tasks=False)

        # Second server instance — recover
        server2 = NousServer(config=server_config)
        try:
            server2.start()
            recovered = server2.recover_tasks()
            assert len(recovered) >= 1
            recovered_task = recovered[0]
            assert recovered_task.current_step == 7
            assert recovered_task.phase == TaskPhase.RECOVERING
        finally:
            server2.stop(drain_tasks=False)



# Systemd integration (config validation)


class TestSystemdConfig:
    def test_service_file_exists(self):
        """Verify the systemd service file exists at the expected location."""
        import os
        service_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "nousd.service"
        )
        # Normalize path
        service_path = os.path.abspath(service_path)
        assert os.path.exists(service_path), f"systemd service not found at {service_path}"

    def test_config_produces_valid_data_dir(self, server_config):
        """Ensure config.data_dir is always a valid path."""
        assert server_config.data_dir
        assert len(server_config.data_dir) > 0



# Batch 1 integration — full startup sequence


class TestBatch1Integration:
    def test_full_startup_sequence(self, server_config):
        """Verify the complete Batch 1 startup sequence works end-to-end."""
        from nous_runtime.kernel.server import NousServer

        server = NousServer(config=server_config)
        try:
            # 1. Start
            health = server.start()
            assert health.status in ("running", "degraded")

            # 2. Register nodes
            for name in ("worker-1", "worker-2"):
                node = Node()
                node.identity.display_name = name
                server.register_node(node)

            # 3. Submit tasks
            for i in range(3):
                task = Task(objective=f"Task {i}")
                server.submit_task(task)

            # 4. Checkpoint a task
            all_tasks = server.task_registry.list()
            first_task = all_tasks.value[0]
            first_task.transition(TaskPhase.PLANNING)
            first_task.transition(TaskPhase.AWAITING_APPROVAL)
            first_task.transition(TaskPhase.DISPATCHING)
            first_task.transition(TaskPhase.RUNNING)
            server.checkpoint_task(first_task.metadata.id)

            # 5. Health check
            health2 = server.health()
            assert health2.nodes_total == 2
            assert health2.tasks_total == 3
            assert health2.checkpoints_total == 1

            # 6. Health to_dict is valid JSON
            d = health2.to_dict()
            json.dumps(d)  # should not raise
        finally:
            server.stop(drain_tasks=False)
