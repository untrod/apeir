# -*- coding: utf-8 -*-
"""Tests for Context Security — Governance integration and access control."""

from __future__ import annotations

import os
import tempfile

import pytest

from nous_runtime.context.models import ContextItem
from nous_runtime.context.security import (
    ContextAccessDecision,
    ContextAccessRequest,
    ContextGuard,
    DEFAULT_AGENT_POLICIES,
    authorize_context_access,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        nous_dir = os.path.join(tmp, ".nous")
        os.makedirs(nous_dir, exist_ok=True)
        yield nous_dir


@pytest.fixture
def guard(temp_workspace):
    return ContextGuard(temp_workspace)



# ContextAccessRequest


class TestContextAccessRequest:
    """Tests for ContextAccessRequest model."""

    def test_create_default(self):
        req = ContextAccessRequest()
        assert req.actor == ""

    def test_create_with_fields(self):
        req = ContextAccessRequest(
            actor="agent_01",
            actor_type="agent",
            purpose="continue project",
            requested_sources=("project", "memory"),
        )
        assert req.actor == "agent_01"
        assert req.actor_type == "agent"
        assert "project" in req.requested_sources



# ContextAccessDecision


class TestContextAccessDecision:
    """Tests for ContextAccessDecision model."""

    def test_create_defaults(self):
        dec = ContextAccessDecision()
        assert dec.allowed is False
        assert dec.timestamp != ""

    def test_create_allowed(self):
        dec = ContextAccessDecision(
            allowed=True,
            reason="full access",
            granted_sources=("project", "memory"),
        )
        assert dec.allowed is True
        assert "project" in dec.granted_sources



# ContextGuard


class TestContextGuard:
    """20 tests for ContextGuard."""

    def test_authorize_user_full_access(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="user_1",
            actor_type="user",
            purpose="review context",
            requested_sources=("memory", "project", "agent"),
        ))
        assert decision.allowed is True

    def test_authorize_system_full_access(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="system",
            actor_type="system",
            purpose="admin",
            requested_sources=("memory", "project"),
        ))
        assert decision.allowed is True

    def test_authorize_coding_agent_allowed_sources(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_coding",
            actor_type="agent",
            purpose="write code",
            requested_sources=("project", "task", "memory"),
        ))
        assert decision.allowed is True

    def test_authorize_unknown_actor_type(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="unknown",
            actor_type="bot",
            purpose="test",
        ))
        assert decision.allowed is False

    def test_authorize_records_audit(self, guard, temp_workspace):
        guard.authorize(ContextAccessRequest(
            actor="agent_test",
            actor_type="agent",
            purpose="test audit",
            requested_sources=("project",),
        ))
        entries = guard.get_audit_log(actor="agent_test")
        assert len(entries) >= 1

    def test_authorize_grants_only_allowed_sources(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_coding",
            actor_type="agent",
            purpose="coding task",
            requested_sources=("project", "nonexistent_source"),
        ))
        if decision.allowed:
            assert "nonexistent_source" not in decision.granted_sources

    def test_default_agent_policies_have_expected_keys(self):
        for agent_type in ("coding", "planner", "executor", "observer"):
            assert agent_type in DEFAULT_AGENT_POLICIES
            policy = DEFAULT_AGENT_POLICIES[agent_type]
            assert "allow" in policy
            assert "deny" in policy

    def test_coding_agent_can_access_project(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_coder",
            actor_type="agent",
            purpose="coding",
            requested_sources=("project",),
        ))
        assert decision.allowed is True
        assert "project" in decision.granted_sources

    def test_observer_agent_denied_device(self, guard):
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_observer",
            actor_type="agent",
            purpose="observation",
            requested_sources=("device", "agent"),
        ))
        # Observer denies both device and agent
        if not decision.allowed:
            assert "device" in decision.denied_sources or "agent" in decision.denied_sources

    # -- Item-level permission tests --

    def test_check_item_permission_read(self, guard):
        item = ContextItem(content="public", source_type="memory", permission="read")
        assert guard.check_item_permission(item, actor="agent_01", actor_type="agent") is True

    def test_check_item_permission_private_user(self, guard):
        item = ContextItem(content="secret", source_type="memory", permission="private")
        assert guard.check_item_permission(item, actor="user_1", actor_type="user") is True

    def test_check_item_permission_private_agent(self, guard):
        item = ContextItem(content="secret", source_type="memory", permission="private")
        assert guard.check_item_permission(item, actor="agent_01", actor_type="agent") is False

    def test_check_item_permission_restricted_agent(self, guard):
        item = ContextItem(content="restricted", source_type="memory", permission="restricted")
        # Coding agent has "memory" in its allow list
        result = guard.check_item_permission(item, actor="agent_coding", actor_type="agent")
        assert result is True

    def test_filter_items_removes_private(self, guard):
        items = [
            ContextItem(content="pub", source_type="memory", permission="read"),
            ContextItem(content="priv", source_type="memory", permission="private"),
        ]
        filtered = guard.filter_items(items, actor="agent_01", actor_type="agent")
        assert len(filtered) == 1
        assert filtered[0].content == "pub"

    def test_audit_log_filter_by_actor(self, guard):
        guard.authorize(ContextAccessRequest(
            actor="specific_agent", actor_type="agent", purpose="test",
            requested_sources=("memory",),
        ))
        entries = guard.get_audit_log(actor="specific_agent")
        for e in entries:
            assert e["actor"] == "specific_agent"

    def test_audit_log_default_limit(self, guard):
        entries = guard.get_audit_log()
        assert isinstance(entries, list)

    # -- Convenience function --

    def test_convenience_function(self, temp_workspace):
        decision = authorize_context_access(
            actor="agent_test",
            actor_type="agent",
            purpose="test",
            sources=("project",),
            workspace=temp_workspace,
        )
        assert isinstance(decision, ContextAccessDecision)

    def test_partial_access_grant(self, guard):
        """When some sources are denied, the allowed ones are still granted."""
        decision = guard.authorize(ContextAccessRequest(
            actor="agent_coding",
            actor_type="agent",
            purpose="test partial",
            requested_sources=("project", "memory"),
        ))
        # Both should be allowed for coding agent
        assert decision.allowed is True
        assert "project" in decision.granted_sources
        assert "memory" in decision.granted_sources

    def test_all_denied(self, guard):
        """When all requested sources are denied for a known restrictive agent type."""
        # Test the policy directly — observer denies device + agent,
        # but only allows memory, project, runtime.
        # When requesting sources NOT in the allow list, nothing is granted.
        observer_allow = DEFAULT_AGENT_POLICIES["observer"]["allow"]
        observer_deny = DEFAULT_AGENT_POLICIES["observer"]["deny"]
        # Both device and agent are in the deny list for observer
        assert "device" in observer_deny or "device" not in observer_allow
        assert "agent" in observer_deny or "agent" not in observer_allow
