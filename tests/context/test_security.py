"""Context security uses authenticated callers and canonical Gate decisions."""

import json
from dataclasses import replace

import pytest

from nous_runtime.context.models import ContextItem
from nous_runtime.context.security import (
    ContextAccessDecision,
    ContextAccessRequest,
    DEFAULT_AGENT_POLICIES,
    authorize_context_access,
)
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.contracts import AuthorizationContext
from tests.context.test_guard_admission import (
    admitted_context as admitted_context_fixture,
    request,
)

admitted_context = admitted_context_fixture


@pytest.fixture
def guard(admitted_context):
    return admitted_context[0]


class TestContextAccessRequest:
    def test_create_default(self):
        assert ContextAccessRequest().authorization_context is None

    def test_create_with_fields(self):
        value = ContextAccessRequest(
            actor="agent_01",
            actor_type="agent",
            purpose="continue project",
            requested_sources=("project", "memory"),
        )
        assert value.actor == "agent_01"
        assert "project" in value.requested_sources


class TestContextAccessDecision:
    def test_create_defaults(self):
        value = ContextAccessDecision()
        assert not value.allowed
        assert value.timestamp and value.decision_id

    def test_create_allowed(self):
        value = ContextAccessDecision(allowed=True, granted_sources=("project",))
        assert value.allowed and value.granted_sources == ("project",)


class TestContextGuard:
    def test_authorize_user_full_access(self, admitted_context):
        guard, _, _ = admitted_context
        owner = _build_context()
        value = guard.authorize(
            request(
                owner,
                actor_type="user",
                requested_sources=("memory", "project", "agent"),
            )
        )
        assert value.allowed
        assert value.granted_sources == ("agent", "memory", "project")

    def test_authorize_system_full_access(self, guard):
        context = AuthorizationContext(
            subject_type="service",
            subject_id="system",
            authn_method="trusted_runtime",
            authn_confidence=0.9,
        )
        assert guard.authorize(request(context, actor_type="system")).allowed

    def test_authorize_coding_agent_allowed_sources(self, admitted_context):
        guard, _, context = admitted_context
        value = guard.authorize(
            request(
                context,
                requested_sources=("project", "task", "memory"),
            )
        )
        assert value.allowed
        assert value.granted_sources == ("memory", "project", "task")

    def test_authorize_unknown_actor_type(self, admitted_context):
        guard, _, context = admitted_context
        assert not guard.authorize(request(context, actor_type="bot")).allowed

    def test_authorize_records_audit(self, admitted_context):
        guard, _, context = admitted_context
        assert guard.authorize(request(context)).allowed
        assert guard.get_audit_log(actor=context.subject_id)[0]["decision"] == "allow"

    def test_authorize_grants_only_allowed_sources(self, admitted_context):
        guard, _, context = admitted_context
        value = guard.authorize(
            request(
                context,
                requested_sources=("project", "nonexistent_source"),
            )
        )
        assert value.allowed and value.granted_sources == ("project",)
        assert value.denied_sources == ("nonexistent_source",)

    def test_default_agent_policies_have_expected_keys(self):
        for policy in DEFAULT_AGENT_POLICIES.values():
            assert "allow" in policy and "deny" in policy

    def test_coding_agent_can_access_project(self, admitted_context):
        guard, _, context = admitted_context
        assert guard.authorize(request(context)).granted_sources == ("project",)

    def test_observer_agent_denied_device(self, admitted_context):
        guard, _, context = admitted_context
        observer = replace(context, subject_id="agent.observer")
        value = guard.authorize(
            request(observer, requested_sources=("device", "agent"))
        )
        assert not value.allowed and value.denied_sources == ("agent", "device")

    def test_check_item_permission_read(self, admitted_context):
        guard, _, context = admitted_context
        item = ContextItem(content="public", source_type="memory")
        assert guard.check_item_permission(
            item,
            context.subject_id,
            "agent",
            authorization_context=context,
            purpose="review memory",
        )

    def test_check_item_permission_private_user(self, guard):
        owner = _build_context()
        item = ContextItem(
            content="private",
            source_type="memory",
            permission="private",
            metadata={"owner_id": owner.subject_id},
        )
        assert guard.check_item_permission(
            item,
            owner.subject_id,
            "user",
            authorization_context=owner,
            purpose="review my memory",
        )

    def test_check_item_permission_private_agent(self, admitted_context):
        guard, _, context = admitted_context
        item = ContextItem(
            content="private", source_type="memory", permission="private"
        )
        assert not guard.check_item_permission(
            item,
            context.subject_id,
            "agent",
            authorization_context=context,
            purpose="review memory",
        )

    def test_restricted_agent_read_requires_canonical_admission(self, admitted_context):
        guard, gate, context = admitted_context
        item = ContextItem(
            content="restricted", source_type="memory", permission="restricted"
        )
        assert not guard.check_item_permission(
            item,
            context.subject_id,
            "agent",
            authorization_context=context,
            purpose="review memory",
        )
        audit = json.loads(guard.get_audit_log()[0]["metadata_json"])
        assert (
            gate.store.get_decision(audit["decision_id"])["action_mode"]
            == "ASK_APPROVAL"
        )

    def test_filter_items_removes_private(self, admitted_context):
        guard, _, context = admitted_context
        items = [
            ContextItem(content="public", source_type="memory"),
            ContextItem(content="private", source_type="memory", permission="private"),
        ]
        assert guard.filter_items(
            items,
            context.subject_id,
            "agent",
            authorization_context=context,
            purpose="review memory",
        ) == [items[0]]

    def test_audit_log_filter_by_actor(self, admitted_context):
        guard, _, context = admitted_context
        guard.authorize(request(context))
        assert all(
            row["actor"] == context.subject_id
            for row in guard.get_audit_log(actor=context.subject_id)
        )

    def test_audit_log_default_limit(self, guard):
        assert isinstance(guard.get_audit_log(), list)

    def test_convenience_function(self, admitted_context):
        guard, _, context = admitted_context
        value = authorize_context_access(
            context.subject_id,
            "agent",
            "review project",
            sources=("project",),
            workspace=guard._workspace,
            authorization_context=context,
        )
        assert value.allowed

    def test_partial_access_grant(self, admitted_context):
        guard, _, context = admitted_context
        observer = replace(context, subject_id="agent.observer")
        value = guard.authorize(
            request(observer, requested_sources=("project", "device"))
        )
        assert value.allowed
        assert value.granted_sources == ("project",) and value.denied_sources == (
            "device",
        )

    def test_all_denied(self, admitted_context):
        guard, _, context = admitted_context
        value = guard.authorize(request(context, requested_sources=("unknown",)))
        assert not value.allowed and value.granted_sources == ()
