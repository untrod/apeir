# -*- coding: utf-8 -*-
"""Tests for Agent Network — 25 tests."""

from __future__ import annotations

import os
import tempfile

import pytest
from nous_runtime.network.models import AgentNode
from nous_runtime.network.registry import NetworkRegistry
from nous_runtime.network.discovery import AgentDiscovery
from nous_runtime.network.health import NetworkHealth
from nous_runtime.network.session import AgentMessage, MessageType


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, ".nous")


@pytest.fixture
def registry(workspace):
    return NetworkRegistry(workspace)


class TestAgentNode:
    def test_create(self):
        n = AgentNode(name="test", node_type="coding", capabilities=("python",))
        assert n.id.startswith("anode_")
        assert n.status == "offline"

    def test_to_dict(self):
        n = AgentNode(name="test", node_type="coding", capabilities=("python", "rust"))
        d = n.to_dict()
        assert d["name"] == "test"
        assert "python" in d["capabilities"]

    def test_from_dict(self):
        d = {"name": "restored", "node_type": "robot", "capabilities": ["camera"]}
        n = AgentNode.from_dict(d)
        assert n.name == "restored"


class TestNetworkRegistry:
    def test_register_and_get(self, registry):
        n = AgentNode(name="test", node_type="coding", capabilities=("python",))
        assert registry.register(n) is True
        g = registry.get(n.id)
        assert g is not None
        assert g.name == "test"

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_list_empty(self, registry):
        assert registry.list() == []

    def test_list_filter_type(self, registry):
        registry.register(AgentNode(name="a", node_type="coding"))
        registry.register(AgentNode(name="b", node_type="robot"))
        assert len(registry.list(node_type="coding")) == 1

    def test_heartbeat(self, registry):
        n = AgentNode(name="test", node_type="coding")
        registry.register(n)
        assert registry.heartbeat(n.id) is True
        g = registry.get(n.id)
        assert g.status == "online"

    def test_remove(self, registry):
        n = AgentNode(name="test", node_type="coding")
        registry.register(n)
        assert registry.remove(n.id) is True
        assert registry.get(n.id) is None


class TestAgentDiscovery:
    def test_discover_by_capability(self, registry):
        registry.register(AgentNode(name="coder", node_type="coding", capabilities=("python",), status="online"))
        d = AgentDiscovery(registry)
        results = d.find(capability="python")
        assert len(results) >= 1

    def test_discover_no_match(self, registry):
        registry.register(AgentNode(name="coder", node_type="coding", capabilities=("rust",), status="online"))
        d = AgentDiscovery(registry)
        results = d.find(capability="python")
        assert len(results) == 0

    def test_network_summary(self, registry):
        registry.register(AgentNode(name="a", node_type="coding", status="online"))
        d = AgentDiscovery(registry)
        s = d.network_summary()
        assert s["total_nodes"] == 1
        assert s["online_nodes"] >= 1


class TestNetworkHealth:
    def test_check_all(self, registry):
        registry.register(AgentNode(name="a", node_type="coding", status="online"))
        h = NetworkHealth(registry)
        reports = h.check_all()
        assert len(reports) >= 1

    def test_network_health(self, registry):
        registry.register(AgentNode(name="a", node_type="coding", status="online"))
        h = NetworkHealth(registry)
        nh = h.network_health()
        assert "total_nodes" in nh


class TestAgentMessage:
    def test_request(self):
        msg = AgentMessage.request(source="a1", target="a2", payload={"key": "val"})
        assert msg.msg_type == MessageType.REQUEST.value
        assert msg.source_agent == "a1"

    def test_response(self):
        req = AgentMessage.request(source="a1", target="a2", payload={"q": "?"})
        resp = AgentMessage.response(req, payload={"a": "!"})
        assert resp.msg_type == MessageType.RESPONSE.value
        assert resp.correlation_id == req.id

    def test_event(self):
        msg = AgentMessage.event(source="a1", event_type="completed", data={"ok": True})
        assert msg.msg_type == MessageType.EVENT.value
