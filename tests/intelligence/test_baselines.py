# -*- coding: utf-8 -*-
"""Tests for baseline algorithms."""

import pytest


class TestBaselineImplementations:
    @pytest.fixture
    def available_models(self):
        return [
            {"model_id": "gpt-4o", "capability_level": "expert", "cost_per_1k_tokens": 0.015, "avg_latency_ms": 800, "success_rate": 0.95, "endpoint_type": "cloud"},
            {"model_id": "claude-sonnet", "capability_level": "expert", "cost_per_1k_tokens": 0.010, "avg_latency_ms": 600, "success_rate": 0.94, "endpoint_type": "cloud"},
            {"model_id": "deepseek-chat", "capability_level": "advanced", "cost_per_1k_tokens": 0.002, "avg_latency_ms": 1200, "success_rate": 0.88, "endpoint_type": "cloud"},
            {"model_id": "ollama-llama3", "capability_level": "competent", "cost_per_1k_tokens": 0.0, "avg_latency_ms": 3000, "success_rate": 0.82, "endpoint_type": "local"},
        ]

    def test_fixed_strongest_selects_expert(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import FixedStrongestModel
        b = FixedStrongestModel()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["capability_level"] == "expert"

    def test_fixed_cheapest_selects_min_cost(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import FixedCheapestModel
        b = FixedCheapestModel()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["cost_per_1k_tokens"] == 0.0  # local model

    def test_fixed_fastest_selects_min_latency(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import FixedFastestModel
        b = FixedFastestModel()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["model_id"] == "claude-sonnet"  # 600ms

    def test_random_model_selects_something(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import RandomModel
        b = RandomModel()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["model_id"] in [m["model_id"] for m in available_models]

    def test_round_robin_cycles(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import RoundRobin
        b = RoundRobin()
        first = b.select_model({}, available_models)
        second = b.select_model({}, available_models)
        assert first is not None
        assert second is not None
        # Should cycle (first index 0, second index 1)
        assert first["model_id"] == available_models[0]["model_id"]
        assert second["model_id"] == available_models[1]["model_id"]

    def test_manual_rule_coding_task(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import ManualRuleRouter
        b = ManualRuleRouter()
        selected = b.select_model(
            {"task_type": "code_generation", "description": "Write some Python code"},
            available_models,
        )
        assert selected is not None
        assert "gpt" in selected["model_id"].lower() or "claude" in selected["model_id"].lower()

    def test_local_only_selects_local(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import LocalOnly
        b = LocalOnly()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["endpoint_type"] == "local"

    def test_cloud_only_selects_cloud(self, available_models):
        from nous_runtime.intelligence.baselines.implementations import CloudOnly
        b = CloudOnly()
        selected = b.select_model({}, available_models)
        assert selected is not None
        assert selected["endpoint_type"] == "cloud"

    def test_single_agent_topology(self):
        from nous_runtime.intelligence.baselines.implementations import SingleAgent
        b = SingleAgent()
        assert b.agent_topology({}) == ["worker"]

    def test_pwr_topology(self):
        from nous_runtime.intelligence.baselines.implementations import FixedPlannerWorkerReviewer
        b = FixedPlannerWorkerReviewer()
        assert b.agent_topology({}) == ["planner", "worker", "reviewer"]

    def test_no_verification(self):
        from nous_runtime.intelligence.baselines.implementations import NoVerification
        b = NoVerification()
        assert b.should_verify({}) is False

    def test_always_verify(self):
        from nous_runtime.intelligence.baselines.implementations import AlwaysVerify
        b = AlwaysVerify()
        assert b.should_verify({}) is True

    def test_all_14_baselines_registered(self):
        from nous_runtime.intelligence.baselines.implementations import ALL_BASELINES
        assert len(ALL_BASELINES) == 14
        names = {b.name for b in ALL_BASELINES}
        expected = {
            "fixed_strongest", "fixed_cheapest", "fixed_fastest",
            "random_model", "round_robin", "manual_rule", "weighted_scalar",
            "single_agent", "fixed_planner_worker_reviewer", "fixed_node",
            "no_verification", "always_verify", "local_only", "cloud_only",
        }
        assert names == expected

    def test_baseline_registry_loads_builtins(self):
        from nous_runtime.intelligence.baselines import BaselineRegistry
        registry = BaselineRegistry()
        all_baselines = registry.list_all()
        assert len(all_baselines) == 14
