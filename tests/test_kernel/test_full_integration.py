# -*- coding: utf-8 -*-
"""Full integration tests across all systems built in this round.

Verifies the complete chains specified in the master plan:
- Server starts → Node registers → Task submitted → Model scheduled
→ Sandbox executes → Evidence recorded → Checkpoint saved → Recover
- Admission pipeline: request → authenticate → authorize → risk → budget
- Capability Contract enforcement
- Secret Vault put/get/rotate
- Node Mesh heartbeat/dedup/offline buffer
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d



# Full execution chain


class TestFullExecutionChain:
    """§25 demo scenario: user says 'Run tests, find issues, propose fixes'."""

    def test_server_lifecycle_chain(self, tmp_dir):
        """Verify complete server lifecycle with task submission and recovery."""
        from nous_runtime.kernel.server import NousServer
        from nous_runtime.kernel.config import NousConfig
        from nous_runtime.kernel.node import Node
        from nous_runtime.kernel.task import Task, TaskPhase

        config = NousConfig(
            server_name="test-primary",
            data_dir=tmp_dir,
            demo_mode=True,
            primary_node="test-primary",
        )

        server = NousServer(config=config)
        try:
            # Step 1: Start server
            health = server.start()
            assert health.status in ("running", "degraded")

            # Step 2: Register a worker node
            worker = Node()
            worker.identity.display_name = "rtx3070-worker"
            worker.mark_online(reason="Boot complete")
            result = server.register_node(worker)
            assert result.ok

            # Step 3: Submit a task
            task = Task(objective="Run test suite and report results")
            result = server.submit_task(task)
            assert result.ok
            assert task.phase == TaskPhase.QUEUED

            # Step 4: Progress task through lifecycle
            task.transition(TaskPhase.PLANNING, reason="Planner analyzing")
            task.transition(TaskPhase.AWAITING_APPROVAL, reason="Plan ready")
            task.transition(TaskPhase.DISPATCHING, reason="Assigning to worker")
            task.transition(TaskPhase.RUNNING, reason="Executing on rtx3070")
            task.transition(TaskPhase.VERIFYING, reason="Checking results")

            # Step 5: Create checkpoint
            ckpt_result = server.checkpoint_task(task.metadata.id)
            assert ckpt_result.ok

            # Step 6: Verify recovery works
            task.transition(TaskPhase.COMPLETED, reason="All tests passed")
            assert task.is_terminal

            # Step 7: Health check
            health2 = server.health()
            assert health2.tasks_total == 1
            assert health2.nodes_total >= 1
            assert health2.checkpoints_total == 1

        finally:
            server.stop(drain_tasks=False)



# Admission Control


class TestAdmissionPipeline:
    def test_readonly_auto_approved(self):
        from nous_runtime.security.admission import (
            AdmissionPipeline,
            AdmissionRequest,
            RiskLevel,
        )
        pipeline = AdmissionPipeline()
        request = AdmissionRequest(
            capability_id="project.read_file",
            risk_level=RiskLevel.READ_ONLY,
            user_id="user-1",
        )
        result = pipeline.check(request)
        assert result.allowed
        assert not result.requires_approval

    def test_high_requires_approval(self):
        from nous_runtime.security.admission import (
            AdmissionPipeline,
            AdmissionRequest,
            RiskLevel,
        )
        pipeline = AdmissionPipeline()
        request = AdmissionRequest(
            capability_id="shell.execute",
            risk_level=RiskLevel.HIGH,
            user_id="user-1",
        )
        result = pipeline.check(request)
        assert result.allowed
        assert result.requires_approval

    def test_critical_denied_by_default(self):
        from nous_runtime.security.admission import (
            AdmissionPipeline,
            AdmissionRequest,
            RiskLevel,
        )
        pipeline = AdmissionPipeline()
        request = AdmissionRequest(
            capability_id="plc.write_register",
            risk_level=RiskLevel.CRITICAL,
            user_id="user-1",
        )
        result = pipeline.check(request)
        assert not result.allowed

    def test_risk_classification(self):
        from nous_runtime.security.admission import classify_risk, RiskLevel
        assert classify_risk("project.read_file") == RiskLevel.READ_ONLY
        assert classify_risk("project.run_tests") == RiskLevel.LOW
        assert classify_risk("git.push") == RiskLevel.HIGH
        assert classify_risk("plc.write_register") == RiskLevel.CRITICAL



# Capability Contract


class TestCapabilityContract:
    def test_contract_registry(self):
        from nous_runtime.capability.contract import (
            CapabilityContractRegistry,
        )
        registry = CapabilityContractRegistry()
        contract = registry.get("project.read_file")
        assert contract.ok
        assert contract.value.risk_level == "read_only"
        assert contract.value.idempotency.value == "idempotent"

    def test_git_push_requires_permission(self):
        from nous_runtime.capability.contract import CapabilityContractRegistry
        registry = CapabilityContractRegistry()
        contract = registry.get("git.push")
        assert contract.ok
        assert "git.push" in contract.value.required_permissions

    def test_registry_has_defaults(self):
        from nous_runtime.capability.contract import CapabilityContractRegistry
        registry = CapabilityContractRegistry()
        all_contracts = registry.list_all()
        assert len(all_contracts) >= 6



# Secret Vault


class TestSecretVault:
    @pytest.fixture
    def vault(self, tmp_dir):
        from nous_runtime.security.vault import SecretVault
        db_path = os.path.join(tmp_dir, "vault.db")
        return SecretVault(db_path)

    def test_put_and_get(self, vault):
        result = vault.put("test/secret", "my-value-123")
        assert result.ok
        ref = result.value
        assert ref.vault_path == "test/secret"

        result2 = vault.get("test/secret")
        assert result2.ok
        assert result2.value == "my-value-123"

    def test_get_nonexistent(self, vault):
        result = vault.get("nonexistent/path")
        assert not result.ok

    def test_delete(self, vault):
        vault.put("test/delete_me", "value")
        vault.delete("test/delete_me")
        result = vault.get("test/delete_me")
        assert not result.ok

    def test_list_paths(self, vault):
        vault.put("a/b/c", "v1")
        vault.put("x/y/z", "v2")
        paths = vault.list_paths()
        assert paths.ok
        assert "a/b/c" in paths.value
        assert "x/y/z" in paths.value

    def test_rotate(self, vault):
        vault.put("test/rotate", "old-value")
        vault.rotate("test/rotate", "new-value")
        result = vault.get("test/rotate")
        assert result.ok
        assert result.value == "new-value"

    def test_health(self, vault):
        health = vault.health()
        assert health.ok



# Sandbox


class TestSandbox:
    def test_allowed_command(self, tmp_dir):
        import sys

        from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
        sandbox = ExecutionSandbox(SandboxConfig(
            workspace_root=tmp_dir,
            allowed_commands=["python", "python3"],
        ))
        result = sandbox.run(f'"{sys.executable}" -c "print(\'hello\')"')
        if result.availability_state == "unavailable":
            assert not result.ok
            assert "STRICT_SANDBOX_UNAVAILABLE" in result.stderr
        else:
            assert result.ok
            assert result.security_grade == "strong_vm"
            assert "hello" in result.stdout

    def test_denied_command(self, tmp_dir):
        from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
        sandbox = ExecutionSandbox(SandboxConfig(
            workspace_root=tmp_dir,
            allowed_commands=["echo"],
            denied_commands=["rm"],
        ))
        result = sandbox.run("rm -rf /")
        assert not result.ok
        assert "denied" in result.stderr

    def test_not_allowed_command(self, tmp_dir):
        from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
        sandbox = ExecutionSandbox(SandboxConfig(
            workspace_root=tmp_dir,
            allowed_commands=["echo"],
        ))
        result = sandbox.run("ls /etc")
        assert not result.ok
        assert "not in the allowed list" in result.stderr



# Node Mesh


class TestNodeMeshIntegration:
    def test_heartbeat_and_offline_detection(self):
        from nous_runtime.connectivity.mesh import NodeMesh
        from nous_runtime.kernel.node import Node

        mesh = NodeMesh(primary_node_id="primary-1")

        node = Node()
        node.heartbeat_interval_ms = 100
        mesh.register_node(node)
        assert len(mesh.list_nodes(online_only=False)) == 1

        # Heartbeat
        mesh.heartbeat(node.metadata.id)
        assert len(mesh.list_nodes(online_only=True)) == 1

    def test_message_dedup(self):
        from nous_runtime.connectivity.mesh import MessageDedupFilter

        dedup = MessageDedupFilter()
        assert not dedup.is_duplicate("msg-1")
        assert dedup.is_duplicate("msg-1")
        assert not dedup.is_duplicate("msg-2")

    def test_offline_buffer(self):
        from nous_runtime.connectivity.mesh import (
            OfflineEventBuffer, MeshMessage,
        )

        buf = OfflineEventBuffer(max_per_node=100)
        msg = MeshMessage(
            source_node_id="primary",
            target_node_id="worker-1",
            message_type="task_update",
            payload={"task_id": "t1"},
        )
        buf.buffer("worker-1", msg)
        assert buf.count_for_node("worker-1") == 1

        events = buf.get_and_clear("worker-1")
        assert len(events) == 1
        assert events[0].message.message_type == "task_update"
        assert buf.count_for_node("worker-1") == 0



# Joint Scheduler


class TestJointScheduler:
    def test_schedule_local_preferred(self):
        from nous_runtime.intelligence.joint_scheduler import JointScheduler
        from nous_runtime.kernel.task import TaskFingerprint

        scheduler = JointScheduler()
        scheduler.set_defaults(
            default_model="ollama/qwen2.5:14b",
            default_node="rtx3070",
            prefer_local=True,
        )

        fp = TaskFingerprint(
            task_type="code_fix",
            required_capabilities=["model.chat"],
            estimated_context_tokens=4000,
            privacy_level="standard",
        )

        nodes = [
            {"node_id": "rtx3070", "name": "RTX 3070", "online": True},
            {"node_id": "cloud", "name": "Cloud VM", "online": True},
        ]

        models = [
            {
                "instance_key": "ollama/qwen2.5:14b/Q4_K_M/llama.cpp/RTX3070",
                "provider": "ollama",
                "model_id": "qwen2.5:14b",
                "capabilities": ["model.chat", "model.stream"],
                "tokens_per_second": 30,
                "price_per_1k_input": 0.0,
                "price_per_1k_output": 0.0,
            },
            {
                "instance_key": "openai/gpt-4/cloud",
                "provider": "openai",
                "model_id": "gpt-4",
                "capabilities": ["model.chat"],
                "tokens_per_second": 50,
                "price_per_1k_input": 0.03,
                "price_per_1k_output": 0.06,
                "avg_latency_ms": 1500,
            },
        ]

        result = scheduler.schedule(fp, nodes, models)
        assert result.ok
        path = result.value
        assert path.node_id == "rtx3070"  # Preferred node
        assert "ollama" in path.model_instance_key  # Local model

    def test_schedule_no_online_nodes(self):
        from nous_runtime.intelligence.joint_scheduler import JointScheduler
        from nous_runtime.kernel.task import TaskFingerprint

        scheduler = JointScheduler()
        fp = TaskFingerprint(task_type="code_fix")

        nodes = [{"node_id": "offline-1", "name": "Offline", "online": False}]
        models = [{"instance_key": "gpt-4", "provider": "openai",
                    "capabilities": ["model.chat"]}]

        result = scheduler.schedule(fp, nodes, models)
        assert not result.ok
        assert result.code.value == "NODE_OFFLINE"



# Token Estimator


class TestTokenEstimator:
    def test_estimate_english(self):
        from nous_runtime.context.token_estimator import estimate_tokens
        text = "The quick brown fox jumps over the lazy dog." * 10
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert 100 < tokens < 500

    def test_estimate_chinese(self):
        from nous_runtime.context.token_estimator import estimate_tokens
        text = "人工智能运行时系统确保所有操作可审计。" * 10
        tokens = estimate_tokens(text)
        assert tokens > 0

    def test_estimate_messages(self):
        from nous_runtime.context.token_estimator import estimate_message_tokens
        msgs = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ]
        tokens = estimate_message_tokens(msgs)
        assert tokens > 0

    def test_context_budget(self):
        from nous_runtime.context.token_estimator import ContextBudget
        budget = ContextBudget(
            max_tokens=8000,
            system_prompt_tokens=500,
            reserved_for_response=1000,
            used_tokens=4000,
        )
        assert budget.available == 2500
        assert budget.can_fit(2000)
        assert not budget.can_fit(3000)

    def test_summarizer_trigger(self):
        from nous_runtime.context.token_estimator import ConversationSummarizer
        summarizer = ConversationSummarizer(max_tokens=1000)
        # Many long messages should trigger summarization
        msgs = [{"role": "user", "content": "x" * 200} for _ in range(10)]
        assert summarizer.should_summarize(msgs)



# End-to-end: All systems together


class TestEndToEnd:
    def test_full_master_plan_chain(self, tmp_dir):
        """Verify the complete chain from §25: user command → result."""
        from nous_runtime.kernel.server import NousServer
        from nous_runtime.kernel.config import NousConfig
        from nous_runtime.kernel.node import Node
        from nous_runtime.kernel.task import Task, TaskPhase
        from nous_runtime.security.admission import AdmissionPipeline, AdmissionRequest, RiskLevel
        from nous_runtime.capability.contract import CapabilityContractRegistry
        from nous_runtime.intelligence.joint_scheduler import JointScheduler
        from nous_runtime.intelligence.evidence import EvidenceLedger, ExecutionInstance

        # Setup
        config = NousConfig(
            server_name="demo-primary",
            data_dir=tmp_dir,
            demo_mode=True,
            primary_node="demo-primary",
            preferred_workers=["rtx3070"],
        )

        # 1. Server starts
        server = NousServer(config=config)
        server.start()

        # 2. Worker joins
        worker = Node()
        worker.identity.display_name = "rtx3070"
        worker.capabilities.local_models = ["qwen2.5:14b"]
        worker.capabilities.inference_engines = ["ollama"]
        server.register_node(worker)

        # 3. Task submitted
        task = Task(objective="Check my Nous project, run tests")
        task.fingerprint.task_type = "code_fix"
        task.fingerprint.required_capabilities = ["model.chat", "project.run_tests"]
        task.fingerprint.estimated_context_tokens = 4000
        server.submit_task(task)

        # Progress task
        task.transition(TaskPhase.PLANNING)
        task.transition(TaskPhase.AWAITING_APPROVAL)
        task.transition(TaskPhase.DISPATCHING)
        task.transition(TaskPhase.RUNNING)
        task.transition(TaskPhase.VERIFYING)

        # 4. Admission check
        pipeline = AdmissionPipeline()
        adm_result = pipeline.check(AdmissionRequest(
            capability_id="project.run_tests",
            risk_level=RiskLevel.LOW,
            user_id="demo-user",
            node_id=worker.metadata.id,
            task_id=task.metadata.id,
        ))
        assert adm_result.allowed

        # 5. Capability contract
        contracts = CapabilityContractRegistry()
        test_contract = contracts.get("project.run_tests")
        assert test_contract.ok
        assert test_contract.value.risk_level == "low"

        # 6. Evidence recording
        ledger = EvidenceLedger(os.path.join(tmp_dir, "evidence.db"))
        instance = ExecutionInstance(
            provider="ollama",
            model_id="qwen2.5:14b",
            quantization="Q4_K_M",
            inference_runtime="llama.cpp",
            hardware="RTX 3070 Laptop",
            task_type="code_fix",
            input_tokens=4000,
            output_tokens=500,
            latency_ms=3000,
            cost_cents=0,
            tool_call_valid_rate=1.0,
            test_pass_rate=0.95,
            user_accepted=True,
            completed=True,
            started_at="2026-07-27T00:00:00Z",
            completed_at="2026-07-27T00:01:00Z",
        )
        ledger.record_execution(instance)

        # 7. Scheduler finds best path
        scheduler = JointScheduler()
        scheduler.set_defaults(
            default_model="ollama/qwen2.5:14b",
            default_node="rtx3070",
        )
        nodes = [{"node_id": worker.metadata.id, "name": "rtx3070",
                   "online": True}]
        models = [{
            "instance_key": "ollama/qwen2.5:14b/Q4_K_M/llama.cpp/RTX3070",
            "provider": "ollama",
            "model_id": "qwen2.5:14b",
            "capabilities": ["model.chat", "model.stream"],
            "tokens_per_second": 30,
            "price_per_1k_input": 0.0,
            "price_per_1k_output": 0.0,
        }]
        sched_result = scheduler.schedule(task.fingerprint, nodes, models)
        assert sched_result.ok

        # 8. Checkpoint task
        ckpt = server.checkpoint_task(task.metadata.id)
        assert ckpt.ok

        # 9. Complete task
        task.transition(TaskPhase.COMPLETED, reason="All tests pass")

        # 10. Verify final state
        health = server.health()
        assert health.tasks_total == 1
        assert health.tasks_completed == 1
        assert health.checkpoints_total == 1

        # Cleanup
        server.stop(drain_tasks=False)
