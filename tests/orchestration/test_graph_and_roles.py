# -*- coding: utf-8 -*-
"""Tests for orchestration: graph compiler, roles, assignment, arbitration, credit."""



class TestGraphCompiler:
    def test_compiles_code_audit_with_review(self):
        from nous_runtime.orchestration import GraphCompiler, validate_dag
        compiler = GraphCompiler()
        graph = compiler.compile({"task_type": "code_audit", "complexity": "high"})
        assert "review" in graph.nodes
        valid, msg = validate_dag(graph)
        assert valid, msg

    def test_compiles_all_task_types(self):
        from nous_runtime.orchestration import GraphCompiler, validate_dag
        compiler = GraphCompiler()
        for tt in ["code_audit", "test_generation", "research", "multi_node", "general"]:
            graph = compiler.compile({"task_type": tt, "complexity": "medium"})
            valid, msg = validate_dag(graph)
            assert valid, f"{tt}: {msg}"
            assert len(graph.nodes) >= 1

    def test_rejects_cycle(self):
        from nous_runtime.orchestration import TaskGraph, TaskNode, validate_dag
        graph = TaskGraph(graph_id="cycle_test")
        graph.nodes = {
            "a": TaskNode(node_id="a", dependencies=["b"]),
            "b": TaskNode(node_id="b", dependencies=["a"]),
        }
        valid, msg = validate_dag(graph)
        assert not valid
        assert "cycle" in msg.lower() or "Cycle" in msg


class TestRoleGenerator:
    def test_code_audit_high_risk_generates_reviewer(self):
        from nous_runtime.orchestration import RoleGenerator
        gen = RoleGenerator()
        roles = gen.generate({"task_type": "code_audit", "complexity": "high", "risk_class": "critical"})
        assert any(r.authority_level == "reviewer" for r in roles)

    def test_default_task_has_worker(self):
        from nous_runtime.orchestration import RoleGenerator
        gen = RoleGenerator()
        roles = gen.generate({"task_type": "general", "complexity": "low"})
        assert len(roles) >= 1
        assert roles[0].authority_level == "worker"


class TestAssignmentEngine:
    def test_assigns_best_fit(self):
        from nous_runtime.orchestration import AssignmentEngine, AgentRole
        engine = AssignmentEngine()
        roles = [AgentRole(role_id="worker", required_capabilities=["code_generation"])]
        models = [{"model_id": "gpt-4o", "status": "healthy", "cost_per_1k_tokens": 0.015, "avg_latency_ms": 800, "success_rate": 0.95, "capabilities": "code_generation", "privacy_class": "internal"}]
        nodes = [{"node_id": "node1", "free_memory_mb": 8192}]
        assignments = engine.assign(roles, models, nodes, {"min_memory_mb": 512})
        assert len(assignments) == 1
        assert assignments[0].model_id == "gpt-4o"


class TestArbitration:
    def test_deterministic_wins(self):
        from nous_runtime.orchestration import Arbiter
        arbiter = Arbiter()
        decision = arbiter.arbitrate(
            {"agent_a": "result_a", "agent_b": "result_b"},
            {"agent_a": {"deterministic_pass": True, "no_errors": True}},
        )
        assert decision.winner == "agent_a"

    def test_single_output_no_conflict(self):
        from nous_runtime.orchestration import Arbiter
        arbiter = Arbiter()
        decision = arbiter.arbitrate({"agent_a": "result"})
        assert decision.winner == "agent_a"
        assert decision.method == "no_conflict"


class TestCreditAssigner:
    def test_assigns_credit(self):
        from nous_runtime.orchestration import CreditAssigner
        assigner = CreditAssigner()
        report = assigner.assign(
            "task_1",
            ["agent_a", "agent_b"],
            {"agent_a": {"status": "success", "verification": "pass"}, "agent_b": {"status": "success"}},
            True,
        )
        assert "agent_a" in report.agent_contributions
        assert report.overall_success
