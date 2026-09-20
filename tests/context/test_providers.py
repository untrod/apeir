# -*- coding: utf-8 -*-
"""Tests for Context Providers — Memory, Project, Agent, Device, Decision."""

from __future__ import annotations


from nous_runtime.context.providers.agent import AgentProvider
from nous_runtime.context.providers.decision import DecisionProvider
from nous_runtime.context.providers.device import DeviceProvider
from nous_runtime.context.providers.memory import MemoryProvider
from nous_runtime.context.providers.project import ProjectProvider
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth


class TestMemoryProvider:
    """Tests for MemoryProvider."""

    def test_source_type(self):
        p = MemoryProvider()
        assert p.source_type == ContextSource.MEMORY.value

    def test_collect_returns_list(self):
        p = MemoryProvider()
        items = p.collect()
        assert isinstance(items, list)

    def test_collect_with_limit(self):
        p = MemoryProvider()
        items = p.collect(limit=5)
        assert len(items) <= 5

    def test_collect_with_hint(self):
        p = MemoryProvider()
        items = p.collect(request_hint="test query")
        assert isinstance(items, list)

    def test_collect_items_have_source_type(self):
        p = MemoryProvider()
        items = p.collect(limit=10)
        for item in items:
            assert item.source_type == ContextSource.MEMORY.value

    def test_health_returns_provider_health(self):
        p = MemoryProvider()
        health = p.health()
        assert isinstance(health, ProviderHealth)
        assert health.source == ContextSource.MEMORY.value

    def test_explain_returns_dict(self):
        p = MemoryProvider()
        result = p.explain(["ctx_001", "ctx_002"])
        assert isinstance(result, dict)
        assert "ctx_001" in result


class TestProjectProvider:
    """Tests for ProjectProvider."""

    def test_source_type(self):
        p = ProjectProvider()
        assert p.source_type == ContextSource.PROJECT.value

    def test_collect_returns_list(self):
        p = ProjectProvider()
        items = p.collect()
        assert isinstance(items, list)

    def test_collect_with_hint(self):
        p = ProjectProvider()
        items = p.collect(request_hint="project status")
        assert isinstance(items, list)

    def test_health_returns_provider_health(self):
        p = ProjectProvider()
        health = p.health()
        assert isinstance(health, ProviderHealth)
        assert health.source == ContextSource.PROJECT.value

    def test_explain_returns_dict(self):
        p = ProjectProvider()
        result = p.explain(["ctx_001"])
        assert isinstance(result, dict)


class TestAgentProvider:
    """Tests for AgentProvider."""

    def test_source_type(self):
        p = AgentProvider()
        assert p.source_type == ContextSource.AGENT.value

    def test_collect_returns_list(self):
        p = AgentProvider()
        items = p.collect()
        assert isinstance(items, list)

    def test_collect_with_limit(self):
        p = AgentProvider()
        items = p.collect(limit=3)
        assert len(items) <= 3

    def test_health_returns_provider_health(self):
        p = AgentProvider()
        health = p.health()
        assert isinstance(health, ProviderHealth)
        assert health.source == ContextSource.AGENT.value

    def test_explain_returns_dict(self):
        p = AgentProvider()
        result = p.explain(["ctx_001"])
        assert isinstance(result, dict)


class TestDeviceProvider:
    """Tests for DeviceProvider."""

    def test_source_type(self):
        p = DeviceProvider()
        assert p.source_type == ContextSource.DEVICE.value

    def test_collect_returns_list(self):
        p = DeviceProvider()
        items = p.collect()
        assert isinstance(items, list)

    def test_collect_graceful_degradation(self):
        p = DeviceProvider()
        items = p.collect(limit=10)
        # Should not raise even if no devices are found
        assert isinstance(items, list)

    def test_health_returns_provider_health(self):
        p = DeviceProvider()
        health = p.health()
        assert isinstance(health, ProviderHealth)
        assert health.source == ContextSource.DEVICE.value

    def test_explain_returns_dict(self):
        p = DeviceProvider()
        result = p.explain(["ctx_001"])
        assert isinstance(result, dict)


class TestDecisionProvider:
    """Tests for DecisionProvider."""

    def test_source_type(self):
        p = DecisionProvider()
        assert p.source_type == ContextSource.DECISION.value

    def test_collect_returns_list(self):
        p = DecisionProvider()
        items = p.collect()
        assert isinstance(items, list)

    def test_collect_with_hint(self):
        p = DecisionProvider()
        items = p.collect(request_hint="pending decisions")
        assert isinstance(items, list)

    def test_health_returns_provider_health(self):
        p = DecisionProvider()
        health = p.health()
        assert isinstance(health, ProviderHealth)
        assert health.source == ContextSource.DECISION.value

    def test_explain_returns_dict(self):
        p = DecisionProvider()
        result = p.explain(["ctx_001"])
        assert isinstance(result, dict)
