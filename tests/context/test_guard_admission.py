"""Context reads reuse canonical admission and current owner identity."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.agent.models import AgentIdentity, AgentManifest
from nous_runtime.agent.registry import AgentRegistry
from nous_runtime.context.models import ContextItem
from nous_runtime.context.security import ContextAccessRequest, ContextGuard
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.gate import ExecutionAuthorizationGate
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.governance.store import GovernanceStore
from tests.control_plane.test_human_sessions import (
    human_env as human_env_fixture,
    login,
)

human_env = human_env_fixture


@pytest.fixture
def admitted_context(tmp_path, monkeypatch):
    from nous_runtime.compat.capability import register_capability
    from nous_runtime.governance import gate as gate_module

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "capabilities"))
    assert register_capability(
        "context.read",
        category="software",
        executor_type="runtime",
        side_effect_class="read_only",
        reversibility="reversible",
        idempotent=True,
        model_uncertainty=0.0,
    )
    workspace = tmp_path / "workspace"
    registry = AgentRegistry(workspace)
    registry.register(
        AgentManifest(
            AgentIdentity("agent.coding", "Coding"), metadata={"role": "coding"}
        )
    )
    registry.register(
        AgentManifest(
            AgentIdentity("agent.observer", "Observer"), metadata={"role": "observer"}
        )
    )
    gate = ExecutionAuthorizationGate(
        GovernanceStore(workspace),
        permission_engine=PermissionEngine((PermissionRule("*", "context.read", "*"),)),
    )
    monkeypatch.setattr(gate_module, "_gate_instance", gate)
    context = AuthorizationContext(
        subject_type="agent",
        subject_id="agent.coding",
        authn_method="runtime",
        authn_confidence=0.9,
    )
    return ContextGuard(str(workspace)), gate, context


def request(context, **kwargs):
    value = ContextAccessRequest(
        actor=context.subject_id,
        actor_type="agent",
        purpose="continue the current project",
        context_id="snapshot-1",
        requested_sources=("project",),
    )
    # Also works against the original request contract for the before-fix probes.
    value.authorization_context = context
    for name, field in kwargs.items():
        setattr(value, name, field)
    return value


@pytest.mark.parametrize("mode", ["DENY", "RECOMMEND", "ASK_APPROVAL", "UNKNOWN"])
def test_nonexecution_gate_decisions_deny_every_source(
    admitted_context, monkeypatch, mode
):
    guard, gate, context = admitted_context
    monkeypatch.setattr(
        gate,
        "evaluate",
        lambda *_: SimpleNamespace(
            action_mode=mode,
            allowed=False,
            reason_code="CONTROLLED_DENIAL",
            decision_id="controlled-decision",
        ),
    )
    decision = guard.authorize(request(context))
    assert not decision.allowed
    assert decision.granted_sources == ()
    assert decision.denied_sources == ("project",)


def test_gate_error_denies_and_does_not_copy_exception_material(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    sensitive = "FAKE-PRIVATE-GATE-ERROR"

    def unavailable(*_):
        raise OSError(sensitive)

    monkeypatch.setattr(gate, "evaluate", unavailable)
    decision = guard.authorize(request(context))
    assert not decision.allowed
    assert sensitive not in str(decision)
    assert sensitive not in str(guard.get_audit_log())


@pytest.mark.parametrize("field,value", [("purpose", ""), ("actor", "")])
def test_missing_identity_or_purpose_denies(admitted_context, field, value):
    guard, _, context = admitted_context
    assert not guard.authorize(request(context, **{field: value})).allowed


def test_missing_authorization_context_does_not_invent_identity(admitted_context):
    guard, _, context = admitted_context
    assert not guard.authorize(request(context, authorization_context=None)).allowed


@pytest.mark.parametrize(
    "metadata",
    [{"permission": "private"}, {"permission": "private", "owner_id": "another-owner"}],
)
def test_private_request_requires_explicit_owner_binding(admitted_context, metadata):
    guard, _, _ = admitted_context
    owner = _build_context()
    assert not guard.authorize(
        request(owner, actor_type="user", metadata=metadata)
    ).allowed


def test_actor_claim_cannot_replace_authenticated_subject(admitted_context):
    guard, _, context = admitted_context
    assert not guard.authorize(request(context, actor="agent.observer")).allowed


@pytest.mark.parametrize("confidence", [None, False, float("nan"), float("inf"), 1.1])
def test_unknown_authentication_confidence_denies(admitted_context, confidence):
    guard, _, context = admitted_context
    assert not guard.authorize(
        request(replace(context, authn_confidence=confidence))
    ).allowed


def test_model_claim_cannot_become_context_authority(admitted_context):
    guard, _, context = admitted_context
    assert not guard.authorize(request(replace(context, subject_type="model"))).allowed


@pytest.mark.parametrize("actor_type", [[], {}, None])
def test_malformed_actor_type_is_denied_and_audited(admitted_context, actor_type):
    guard, _, context = admitted_context
    decision = guard.authorize(request(context, actor_type=actor_type))
    assert not decision.allowed
    assert guard.get_audit_log()[0]["decision"] == "deny"


@pytest.mark.parametrize("decision_id", ["", "fabricated-execution-id"])
def test_transient_or_fabricated_execute_response_is_not_admission(
    admitted_context, monkeypatch, decision_id
):
    guard, gate, context = admitted_context
    monkeypatch.setattr(
        gate,
        "evaluate",
        lambda *_: SimpleNamespace(
            action_mode="EXECUTE",
            allowed=True,
            decision_id=decision_id,
        ),
    )
    assert not guard.authorize(request(context)).allowed


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_id", "other-context"),
        ("proposal_hash", "other-proposal"),
        ("action_mode", "DENY"),
        ("allowed", False),
        ("allowed", 1),
    ],
)
def test_stored_decision_must_match_original_context_and_proposal(
    admitted_context, monkeypatch, field, value
):
    guard, gate, context = admitted_context
    read = gate.store.get_decision

    def changed(decision_id):
        persisted = read(decision_id)
        return {**persisted, field: value}

    monkeypatch.setattr(gate.store, "get_decision", changed)
    decision = guard.authorize(request(context))
    assert not decision.allowed
    assert decision.granted_sources == ()


def test_unknown_agent_has_no_default_coding_policy(admitted_context):
    guard, _, context = admitted_context
    unknown = replace(context, subject_id="agent.unknown")
    assert not guard.authorize(request(unknown)).allowed


def test_observer_policy_uses_current_workspace_profile(admitted_context):
    guard, _, context = admitted_context
    observer = replace(context, subject_id="agent.observer")
    decision = guard.authorize(
        request(observer, requested_sources=("project", "device"))
    )
    assert decision.allowed
    assert decision.granted_sources == ("project",)
    assert decision.denied_sources == ("device",)


@pytest.mark.parametrize("failure", [False, OSError("controlled audit failure")])
def test_audit_failure_cannot_return_allowed(admitted_context, monkeypatch, failure):
    guard, _, context = admitted_context

    def audit(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(guard._store, "record_audit", audit)
    assert not guard.authorize(request(context)).allowed


def test_private_owner_is_explicit_and_matches_current_human(admitted_context):
    guard, _, _ = admitted_context
    owner = _build_context()
    for metadata in ({}, {"owner_id": "another-owner"}):
        item = ContextItem(
            content="private fact",
            source_type="memory",
            permission="private",
            metadata=metadata,
        )
        assert not guard.check_item_permission(
            item, actor=owner.subject_id, actor_type="user"
        )


def test_canonical_gate_positive_binds_proposal_and_persists_audit(admitted_context):
    guard, gate, context = admitted_context
    decision = guard.authorize(request(context))
    assert decision.allowed
    canonical = gate.store.get_decision(decision.decision_id)
    assert canonical is not None
    assert canonical["action_mode"] == "EXECUTE"
    proposal = gate.store.get_proposal(canonical["proposal_hash"])
    assert proposal["target_workspace"] == guard._workspace
    assert proposal["affected_resources"] == ["snapshot-1"]
    assert proposal["required_permissions"] == ["context.read"]
    assert gate.store.get_audit_for_decision(decision.decision_id)
    audit = json.loads(guard.get_audit_log()[0]["metadata_json"])
    assert audit["granted_sources"] == ["project"]
    assert audit["authorization_context_id"] == context.context_id


def test_canonical_gate_permission_denial_is_preserved(admitted_context):
    guard, gate, context = admitted_context
    gate.permission_engine.add(
        PermissionRule(context.subject_id, "context.read", "snapshot-1", effect="deny")
    )
    decision = guard.authorize(request(context))
    assert not decision.allowed
    assert (
        gate.store.get_decision(decision.decision_id)["reason_code"]
        == "PERMISSION_DENIED"
    )


def test_disabled_capability_denies_without_default_allow(admitted_context):
    from nous_runtime.compat.capability import set_capability_enabled

    guard, gate, context = admitted_context
    assert set_capability_enabled("context.read", False)
    decision = guard.authorize(request(context))
    assert not decision.allowed
    assert (
        gate.store.get_decision(decision.decision_id)["reason_code"]
        == "CAPABILITY_DISABLED"
    )


def test_purpose_and_sources_bind_the_original_canonical_proposal(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    evaluate = gate.evaluate
    proposals = []

    def record(proposal, identity):
        proposals.append(proposal)
        assert identity is context
        return evaluate(proposal, identity)

    monkeypatch.setattr(gate, "evaluate", record)
    assert guard.authorize(request(context)).allowed
    assert guard.authorize(request(context, purpose="inspect the workspace")).allowed
    assert guard.authorize(request(context, requested_sources=("memory",))).allowed
    assert (
        len(
            {
                proposal.parameter_hash or proposal._compute_hash()
                for proposal in proposals
            }
        )
        == 3
    )
    assert proposals[0].params["sources"] == ["project"]
    assert (
        proposals[0].params["purpose_sha256"] != proposals[1].params["purpose_sha256"]
    )


def test_unknown_or_corrupt_workspace_profile_denies(admitted_context):
    guard, _, context = admitted_context
    registry = AgentRegistry(guard._workspace)
    profile = registry.require(context.subject_id)
    registry.save_profile(
        replace(
            profile, manifest=replace(profile.manifest, metadata={"role": "unknown"})
        )
    )
    assert not guard.authorize(request(context)).allowed
    registry.path.write_text("not valid JSON")
    assert not guard.authorize(request(context)).allowed


def test_other_workspace_has_no_implicit_agent_authority(admitted_context, tmp_path):
    _, _, context = admitted_context
    other = ContextGuard(str(tmp_path / "other-workspace"))
    assert not other.authorize(request(context)).allowed


@pytest.mark.parametrize("value", [None, "project", (None,), ("",)])
def test_malformed_source_requests_fail_closed(admitted_context, value):
    guard, _, context = admitted_context
    assert not guard.authorize(request(context, requested_sources=value)).allowed


def test_attested_local_owner_can_read_private_item_through_canonical_gate(
    admitted_context,
):
    guard, gate, _ = admitted_context
    owner = _build_context()
    item = ContextItem(
        item_id="private-item",
        content="private fact",
        source_type="memory",
        permission="private",
        metadata={"owner_id": owner.subject_id},
    )
    assert guard.check_item_permission(
        item,
        actor=owner.subject_id,
        actor_type="user",
        authorization_context=owner,
        purpose="review my private fact",
    )
    decisions = guard.get_audit_log()
    assert decisions[0]["decision"] == "allow"
    canonical_id = json.loads(decisions[0]["metadata_json"])["decision_id"]
    assert gate.store.get_decision(canonical_id)["action_mode"] == "EXECUTE"
    assert not guard.check_item_permission(
        item,
        actor=owner.subject_id,
        actor_type="user",
        authorization_context=replace(owner),
        purpose="copied identity claim",
    )
    reopened = ContextGuard(guard._workspace)
    assert reopened.check_item_permission(
        item,
        actor=owner.subject_id,
        actor_type="user",
        authorization_context=owner,
        purpose="review after reopening",
    )


@pytest.mark.parametrize("state", ["current", "copied", "revoked", "expired"])
def test_private_remote_read_reuses_current_human_session(
    admitted_context, human_env, monkeypatch, state
):
    from nous_runtime.governance import gate as gate_module

    guard, _, _ = admitted_context
    gate, auth, client, _ = human_env
    auth.permissions.add(PermissionRule("oidc:*:alice", "context.read", "private-item"))
    _, owner = login(auth, client)
    monkeypatch.setattr(gate_module, "_gate_instance", gate)
    item = ContextItem(
        item_id="private-item",
        content="private fact",
        source_type="memory",
        permission="private",
        metadata={"owner_id": owner.subject_id},
    )
    if state == "copied":
        owner = replace(owner)
    elif state == "revoked":
        auth.logout(owner)
    elif state == "expired":
        with gate.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_sessions SET expires_at=0")
    assert guard.check_item_permission(
        item,
        actor=owner.subject_id,
        actor_type="user",
        authorization_context=owner,
        purpose="review my private fact",
    ) is (state == "current")


def test_remote_revocation_during_audit_blocks_delivery(
    admitted_context, human_env, monkeypatch
):
    from nous_runtime.governance import gate as gate_module

    guard, _, _ = admitted_context
    gate, auth, client, _ = human_env
    auth.permissions.add(PermissionRule("oidc:*:alice", "context.read", "snapshot-1"))
    _, owner = login(auth, client)
    monkeypatch.setattr(gate_module, "_gate_instance", gate)
    audit = guard._store.record_audit

    def revoke(*args, **kwargs):
        if kwargs["decision"] == "allow":
            auth.logout(owner)
        return audit(*args, **kwargs)

    monkeypatch.setattr(guard._store, "record_audit", revoke)
    decision = guard.authorize(request(owner, actor_type="user"))
    assert not decision.allowed
    assert decision.granted_sources == ()
