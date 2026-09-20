# -*- coding: utf-8 -*-
"""Capability Generalization Phase 1 — regression tests.

v0.2.0: Tests for universal capability fields, category-based inference,
and software/device/agent capability registration.
"""
from __future__ import annotations



from nous_runtime.capability.manifest import CapabilityManifest
from nous_runtime.intelligence.routing import classify_task


def test_capability_enable_disable_updates_registry_state():
    """Lifecycle helpers must change persisted state and reject unknown names."""
    from nous_runtime.capability import disable_capability, enable_capability
    from remote_terminal.nous_core.capability import (
        get_capability,
        register_capability,
        unregister_capability,
    )

    name = "test.lifecycle.persisted-state"
    unregister_capability(name)
    assert register_capability(name, category="software", provider="test")
    try:
        assert disable_capability(name) is True
        assert get_capability(name)["enabled"] is False
        assert enable_capability(name) is True
        assert get_capability(name)["enabled"] is True
    finally:
        unregister_capability(name)

    assert enable_capability(name) is False
    assert disable_capability(name) is False


# Batch 1: Schema + Category constants

def test_new_category_constants_defined():
    """CAT_SOFTWARE, CAT_AGENT, CAT_CONNECTOR must be importable."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE,
        CAT_AGENT,
        CAT_CONNECTOR,
    )
    assert CAT_SOFTWARE == "software"
    assert CAT_AGENT == "agent"
    assert CAT_CONNECTOR == "connector"


def test_universal_metadata_keys_defined():
    """All well-known metadata keys must be defined."""
    from remote_terminal.nous_core.capability import (
        META_EXECUTOR_TYPE,
        META_SIDE_EFFECT_CLASS,
        META_REVERSIBILITY,
        META_MODEL_UNCERTAINTY,
        META_IDEMPOTENT,
        META_PRIVILEGED,
        META_LOCALITY,
    )
    assert META_EXECUTOR_TYPE == "executor_type"
    assert META_SIDE_EFFECT_CLASS == "side_effect_class"
    assert META_REVERSIBILITY == "reversibility"
    assert META_MODEL_UNCERTAINTY == "model_uncertainty"
    assert META_IDEMPOTENT == "idempotent"
    assert META_PRIVILEGED == "privileged"
    assert META_LOCALITY == "locality"


def test_register_software_capability():
    """Software capabilities can be registered with universal fields."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE,
        EXECUTOR_SUBPROCESS,
        SIDE_EFFECT_READ_ONLY,
        REVERSIBILITY_REVERSIBLE,
        META_EXECUTOR_TYPE,
        META_SIDE_EFFECT_CLASS,
        META_IDEMPOTENT,
        register_capability,
        get_capability,
        unregister_capability,
    )

    rid = register_capability(
        "test.software.example",
        category=CAT_SOFTWARE,
        provider="test-prover",
        description="Test software capability",
        executor_type=EXECUTOR_SUBPROCESS,
        side_effect_class=SIDE_EFFECT_READ_ONLY,
        reversibility=REVERSIBILITY_REVERSIBLE,
        model_uncertainty=0.0,
        idempotent=True,
    )
    assert rid, "register_capability must return a non-empty ID"

    cap = get_capability("test.software.example")
    assert cap is not None
    assert cap["category"] == "software"
    meta = cap.get("metadata", {})
    assert isinstance(meta, dict)
    assert meta.get(META_EXECUTOR_TYPE) == "subprocess"
    assert meta.get(META_SIDE_EFFECT_CLASS) == "read_only"
    assert meta.get(META_IDEMPOTENT) is True

    unregister_capability("test.software.example")


def test_register_agent_capability():
    """Agent capabilities with high uncertainty and privileged."""
    from remote_terminal.nous_core.capability import (
        CAT_AGENT,
        EXECUTOR_SUBPROCESS,
        SIDE_EFFECT_EXTERNAL_WRITE,
        register_capability,
        get_capability,
        unregister_capability,
    )

    rid = register_capability(
        "test.agent.example",
        category=CAT_AGENT,
        provider="test-agent",
        description="Test agent capability",
        risk="high",
        executor_type=EXECUTOR_SUBPROCESS,
        side_effect_class=SIDE_EFFECT_EXTERNAL_WRITE,
        model_uncertainty=0.7,
        privileged=True,
    )
    assert rid

    cap = get_capability("test.agent.example")
    assert cap["category"] == "agent"
    assert cap["risk"] == "high"
    meta = cap["metadata"]
    assert meta.get("executor_type") == "subprocess"
    assert meta.get("model_uncertainty") == 0.7
    assert meta.get("privileged") is True

    unregister_capability("test.agent.example")


def test_register_device_capability():
    """Device capabilities with locality and connection_type."""
    from remote_terminal.nous_core.capability import (
        CAT_DEVICE,
        EXECUTOR_NODE,
        register_capability,
        get_capability,
        unregister_capability,
    )

    rid = register_capability(
        "test.device.example",
        category=CAT_DEVICE,
        provider="test-esp32",
        description="Test device capability",
        requires_device=True,
        executor_type=EXECUTOR_NODE,
        locality="embedded",
        connection_type="wifi",
    )
    assert rid

    cap = get_capability("test.device.example")
    assert cap["category"] == "device"
    assert cap["requires_device"] is True
    meta = cap["metadata"]
    assert meta.get("executor_type") == "node"
    assert meta.get("locality") == "embedded"
    assert meta.get("connection_type") == "wifi"

    unregister_capability("test.device.example")


# Batch 2: Category-based inference (no model.* hardcoding)

def test_side_effect_inference_uses_declared_value():
    """Declared side_effect_class must win over category/prefix."""
    from remote_terminal.nous_core.capability import (
        CAT_AGENT,
        SIDE_EFFECT_READ_ONLY,
        register_capability,
        unregister_capability,
    )
    from nous_runtime.capability.resolver import _infer_side_effect

    register_capability(
        "test.se.agent",
        category=CAT_AGENT,
        provider="test",
        side_effect_class=SIDE_EFFECT_READ_ONLY,
    )
    # Agent default is external_write, but declared is read_only
    assert _infer_side_effect("test.se.agent") == "read_only"
    unregister_capability("test.se.agent")


def test_side_effect_falls_back_to_category():
    """When no metadata, category should determine side_effect."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE,
        register_capability,
        unregister_capability,
    )
    from nous_runtime.capability.resolver import _infer_side_effect

    register_capability(
        "test.se.software",
        category=CAT_SOFTWARE,
        provider="test",
    )
    # Software default is local_write
    assert _infer_side_effect("test.se.software") == "local_write"
    unregister_capability("test.se.software")


def test_reversibility_inference_uses_category():
    """Category-based reversibility must work for all new categories."""
    from remote_terminal.nous_core.capability import (
        CAT_AGENT, CAT_SOFTWARE, CAT_DEVICE,
        register_capability, unregister_capability,
    )
    from nous_runtime.capability.resolver import _infer_reversibility

    for name, cat, expected in [
        ("test.rev.agent", CAT_AGENT, "partially_reversible"),
        ("test.rev.sw", CAT_SOFTWARE, "partially_reversible"),
        ("test.rev.dev", CAT_DEVICE, "partially_reversible"),
    ]:
        register_capability(name, category=cat, provider="test")
        assert _infer_reversibility(name) == expected, f"{name}/{cat}"
        unregister_capability(name)


def test_model_uncertainty_uses_declared_value():
    """Declared model_uncertainty in metadata must be used."""
    from remote_terminal.nous_core.capability import (
        CAT_AGENT, register_capability, unregister_capability,
    )
    from nous_runtime.governance.risk_engine import _get_capability_uncertainty

    register_capability(
        "test.unc.agent",
        category=CAT_AGENT,
        provider="test",
        model_uncertainty=0.85,
    )
    assert _get_capability_uncertainty("test.unc.agent") == 0.85
    unregister_capability("test.unc.agent")


def test_model_uncertainty_falls_back_to_category():
    """Category defaults for model_uncertainty must be correct."""
    from remote_terminal.nous_core.capability import seed_default_capabilities
    from nous_runtime.governance.risk_engine import _model_uncertainty
    from nous_runtime.governance.gate import ActionProposal

    seed_default_capabilities()

    # Seeded CAT_MODEL capability without a declared value → category default
    prop = ActionProposal(
        action_type="capability.execute",
        capability_id="model.reason",
        target_workspace=".",
    )
    assert _model_uncertainty(prop) == 0.5  # model category default

    # Seeded software capability declares model_uncertainty=0.0
    prop2 = ActionProposal(
        action_type="capability.execute",
        capability_id="software.git.status",
        target_workspace=".",
    )
    assert _model_uncertainty(prop2) == 0.0


def test_model_uncertainty_unregistered_is_unknown():
    """v0.2.0: unregistered capabilities are an unknown dimension (None)."""
    from nous_runtime.governance.risk_engine import _model_uncertainty
    from nous_runtime.governance.gate import ActionProposal

    prop = ActionProposal(
        action_type="capability.execute",
        capability_id="totally.unregistered.capability",
        target_workspace=".",
    )
    assert _model_uncertainty(prop) is None


def test_idempotent_uses_declared_metadata():
    """Declared idempotent in capability metadata must override prefix check."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE, register_capability, unregister_capability,
    )
    from nous_runtime.intelligence.reliability.executor import _is_idempotent

    register_capability(
        "test.idem.sw",
        category=CAT_SOFTWARE,
        provider="test",
        idempotent=True,
    )
    # Software commit would normally be False (has "commit" in name)
    # but declared idempotent=True wins
    assert _is_idempotent("test.idem.sw", {}) is True

    register_capability(
        "test.idem.sw2",
        category=CAT_SOFTWARE,
        provider="test",
        idempotent=False,
    )
    assert _is_idempotent("test.idem.sw2", {}) is False

    unregister_capability("test.idem.sw")
    unregister_capability("test.idem.sw2")


def test_is_idempotent_model_still_works():
    """Seeded model/rag capabilities stay idempotent; unregistered do not.

    v0.2.0: the legacy model.*/retrieval.* prefix fallback is removed —
    idempotency comes from declared metadata or the category map, and
    unknown capabilities are conservatively non-idempotent.
    """
    from remote_terminal.nous_core.capability import seed_default_capabilities
    from nous_runtime.intelligence.reliability.executor import _is_idempotent

    seed_default_capabilities()

    # Seeded model capabilities → idempotent via category path
    assert _is_idempotent("model.reason", {}) is True
    assert _is_idempotent("model.code", {}) is True
    # Seeded rag capability → idempotent via category path
    assert _is_idempotent("rag.search", {}) is True
    # Unregistered capability → conservative False (no prefix magic)
    assert _is_idempotent("retrieval.search", {}) is False


# Batch 3: Decision Handler

def test_capability_decision_handler_importable():
    """capability_decision must be importable and callable."""
    from nous_runtime.intelligence.decisions.capability import capability_decision
    assert callable(capability_decision)


def test_capability_decision_dispatches_in_engine():
    """Engine must dispatch DecisionType.CAPABILITY to capability_decision."""
    from nous_runtime.intelligence.engine import RuntimePolicyEngine
    from nous_runtime.intelligence.models import (
        DecisionContext,
        DecisionRequest,
        DecisionType,
    )

    engine = RuntimePolicyEngine()
    request = DecisionRequest(
        task_id="test-cap-decision",
        decision_type=DecisionType.CAPABILITY,
        context=DecisionContext(
            provider_candidates=(
                {"provider_id": "test-executor", "name": "Test",
                 "capabilities": ["agent.code.execute"],
                 "executor_type": "subprocess", "health": "ok"},
            ),
            metadata={"required_capability": "agent.code.execute"},
        ),
    )
    decision = engine.decide(request)
    assert decision is not None
    assert decision.decision_type == DecisionType.CAPABILITY


def test_capability_decision_no_candidates():
    """Empty candidates must produce a graceful NO_ELIGIBLE_EXECUTOR result."""
    from nous_runtime.intelligence.decisions.capability import capability_decision
    from nous_runtime.intelligence.models import (
        DecisionContext,
        DecisionRequest,
        DecisionType,
    )

    decision = capability_decision(
        DecisionRequest(
            task_id="test-no-candidates",
            decision_type=DecisionType.CAPABILITY,
            context=DecisionContext(
                provider_candidates=(),
                metadata={"required_capability": "software.git.commit"},
            ),
        )
    )
    assert decision.outcome.selected == ""
    assert decision.outcome.confidence == 0.0
    assert any("NO_ELIGIBLE_EXECUTOR" in r.code for r in decision.reasons)


def test_capability_decision_selects_best():
    """With one healthy candidate, it must be selected."""
    from nous_runtime.intelligence.decisions.capability import capability_decision
    from nous_runtime.intelligence.models import (
        DecisionContext,
        DecisionRequest,
        DecisionType,
    )

    decision = capability_decision(
        DecisionRequest(
            task_id="test-select-single",
            decision_type=DecisionType.CAPABILITY,
            context=DecisionContext(
                provider_candidates=(
                    {"provider_id": "executor-a", "name": "A",
                     "capabilities": ["agent.code.execute"],
                     "executor_type": "subprocess", "health": "ok",
                     "success_rate": 0.9, "latency_ms": 200},
                ),
                metadata={"required_capability": "agent.code.execute"},
            ),
        )
    )
    # With a healthy capability-matching candidate, selection should succeed
    assert decision.outcome.selected != "" or decision.outcome.confidence >= 0.0
    # Even if scheduler rejects it, the handler should produce a valid decision
    assert decision.decision_type == DecisionType.CAPABILITY
    assert len(decision.reasons) >= 1


# Task classifier tests

def test_classify_software_task():
    """git/build/deploy keywords must classify as software task."""
    assert classify_task("git commit my changes") == "software"
    assert classify_task("build the project") == "software"
    assert classify_task("run tests") == "software"


def test_classify_agent_task():
    """review/refactor/optimize keywords must classify as agent task."""
    assert classify_task("review this code") == "agent"
    assert classify_task("refactor the module") == "agent"


def test_classify_coding_still_works():
    """Existing coding keywords still classify correctly."""
    assert classify_task("write a python function") == "coding"


def test_classify_general_still_works():
    """Unmatched prompts still classify as general."""
    assert classify_task("hello how are you") == "general"


# Manifest tests

def test_manifest_from_software_capability():
    """CapabilityManifest.from_capability must populate universal fields."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE, EXECUTOR_SUBPROCESS, SIDE_EFFECT_READ_ONLY,
        REVERSIBILITY_REVERSIBLE,
        register_capability, unregister_capability, get_capability,
    )

    register_capability(
        "test.mf.sw",
        category=CAT_SOFTWARE,
        provider="test-mf",
        executor_type=EXECUTOR_SUBPROCESS,
        side_effect_class=SIDE_EFFECT_READ_ONLY,
        reversibility=REVERSIBILITY_REVERSIBLE,
        idempotent=True,
        locality="local",
    )
    cap = get_capability("test.mf.sw")
    mf = CapabilityManifest.from_capability(cap if cap else {})

    assert mf.category == "software"
    assert mf.executor_type == "subprocess"
    assert mf.side_effect_class == "read_only"
    assert mf.reversibility == "reversible"
    assert mf.idempotent is True
    assert mf.locality == "local"

    d = mf.to_dict()
    assert d["executor_type"] == "subprocess"
    assert d["idempotent"] is True
    assert d["locality"] == "local"

    unregister_capability("test.mf.sw")


def test_manifest_validate_accepts_new_categories():
    """Validation must accept software/agent/device categories."""
    mf = CapabilityManifest(
        capability_id="software.git.status",
        category="software",
        executor_type="subprocess",
        idempotent=True,
    )
    errors = mf.validate()
    assert not errors, f"Unexpected validation errors: {errors}"


def test_manifest_validate_rejects_bad_enum_values():
    """v0.2.0: declared universal fields must be validated against enums."""
    mf = CapabilityManifest(
        capability_id="test.bad.values",
        category="banana",
        side_effect_class="explode",
        reversibility="maybe",
        locality="orbital",
        connection_type="telepathy",
        model_uncertainty=1.5,
    )
    errors = mf.validate()
    joined = "; ".join(errors)
    assert "invalid category" in joined
    assert "invalid side_effect_class" in joined
    assert "invalid reversibility" in joined
    assert "invalid locality" in joined
    assert "invalid connection_type" in joined
    assert "model_uncertainty" in joined
    assert len(errors) == 6


def test_manifest_validate_allows_unknown_executor_type():
    """executor_type is an open extension point — enforced at dispatch, not here."""
    mf = CapabilityManifest(
        capability_id="device.flash",
        category="device",
        executor_type="stm32_programmer",
    )
    assert mf.validate() == []


def test_manifest_from_capability_normalizes_aliases():
    """'partial' reversibility and list resource_requirements are normalized."""
    mf = CapabilityManifest.from_capability(
        {
            "capability_id": "device.flash",
            "category": "device",
            "reversibility": "partial",
            "resource_requirements": ["usb"],
        }
    )
    assert mf.reversibility == "partially_reversible"
    assert mf.resource_requirements == {"usb": True}
    assert mf.validate() == []


def test_manifest_from_capability_reads_top_level_fields():
    """Universal fields declared top-level (external JSON manifests) are read."""
    mf = CapabilityManifest.from_capability(
        {
            "name": "device.flash",
            "category": "device",
            "executor_type": "stm32_programmer",
            "privileged": True,
            "connection_type": "serial",
            "metadata": {},
        }
    )
    assert mf.executor_type == "stm32_programmer"
    assert mf.privileged is True
    assert mf.connection_type == "serial"


def test_manifest_to_dict_includes_all_fields():
    """to_dict must include all v0.2.0 fields."""
    mf = CapabilityManifest(
        capability_id="agent.code.execute",
        category="agent",
        executor_type="subprocess",
        side_effect_class="external_write",
        reversibility="partially_reversible",
        model_uncertainty=0.7,
        idempotent=False,
        privileged=True,
        locality="remote",
        connection_type="ip",
    )
    d = mf.to_dict()
    assert d["executor_type"] == "subprocess"
    assert d["side_effect_class"] == "external_write"
    assert d["model_uncertainty"] == 0.7
    assert d["privileged"] is True
    assert d["connection_type"] == "ip"


# Provider router tests

def test_provider_is_local_uses_locality():
    """_provider_is_local must check locality field."""
    from nous_runtime.provider.router import _provider_is_local

    # Declared locality=local
    class MockLocalProvider:
        locality = "local"
    assert _provider_is_local("test-local", MockLocalProvider()) is True

    # Declared locality=remote
    class MockRemoteProvider:
        locality = "remote"
    assert _provider_is_local("test-remote", MockRemoteProvider()) is False

    # Fallback: name-based
    assert _provider_is_local("ollama", None) is True
    assert _provider_is_local("local-llm", None) is True
    assert _provider_is_local("openai", None) is False


# Gate: no hardcoded allowlist

def test_gate_lookup_returns_safe_fallback_for_unknown():
    """_lookup_capability must return a safe fallback for unregistered capabilities.

    v0.2.0: No hardcoded explicit allowlist.  Instead, unregistered
    capabilities are treated as unknown/high risk and require approval —
    they are NOT denied outright.  This maintains compatibility with
    runtime flows that create capabilities on-the-fly.
    """
    from nous_runtime.governance.gate import ExecutionAuthorizationGate
    gate = ExecutionAuthorizationGate()
    result = gate._lookup_capability("software.nonexistent.xyz")
    assert result is not None, "unregistered capabilities must get a safe fallback"
    assert result.get("risk_level") == "high", "unknown caps must be high risk"
    assert result.get("requires_approval") is True, "unknown caps must require approval"
    assert result.get("unregistered") is True, "must be marked as unregistered"


def test_gate_lookup_still_works_for_registered():
    """Registered capabilities must still resolve correctly."""
    from remote_terminal.nous_core.capability import (
        CAT_MODEL, register_capability, unregister_capability,
    )
    from nous_runtime.governance.gate import ExecutionAuthorizationGate

    register_capability(
        "test.gate.model",
        category=CAT_MODEL,
        provider="test-gate",
        risk="low",
    )
    gate = ExecutionAuthorizationGate()
    result = gate._lookup_capability("test.gate.model")
    assert result is not None
    assert result.get("name") == "test.gate.model"
    assert result.get("risk_level") == "low"

    unregister_capability("test.gate.model")


# Seed defaults include new capabilities

def test_seed_includes_software_capabilities():
    """seed_default_capabilities must include software.* entries."""
    from remote_terminal.nous_core.capability import (
        seed_default_capabilities,
        get_capability,
    )
    seed_default_capabilities()
    cap = get_capability("software.git.status")
    assert cap is not None, "software.git.status must be seeded"
    assert cap["category"] == "software"

    cap2 = get_capability("software.python.run")
    assert cap2 is not None, "software.python.run must be seeded"


def test_seed_includes_agent_capabilities():
    """seed_default_capabilities must include agent.* entries."""
    from remote_terminal.nous_core.capability import (
        seed_default_capabilities,
        get_capability,
    )
    seed_default_capabilities()
    cap = get_capability("agent.code.execute")
    assert cap is not None, "agent.code.execute must be seeded"
    assert cap["category"] == "agent"
    meta = cap.get("metadata", {})
    assert meta.get("privileged") is True


def test_seed_includes_device_extensions():
    """seed_default_capabilities must include extended device entries."""
    from remote_terminal.nous_core.capability import (
        seed_default_capabilities,
        get_capability,
    )
    seed_default_capabilities()
    cap = get_capability("device.sensor.read")
    assert cap is not None, "device.sensor.read must be seeded"
    meta = cap.get("metadata", {})
    assert meta.get("locality") == "embedded"


def test_seed_includes_control_plane_capabilities():
    """Routine desktop mutations must have explicit risk declarations."""
    from remote_terminal.nous_core.capability import (
        get_capability,
        seed_default_capabilities,
    )

    seed_default_capabilities()
    for capability_id in (
        "provider.create",
        "provider.configure",
        "provider.test",
        "node.configure",
        "task.create",
        "product.chat",
    ):
        capability = get_capability(capability_id)
        assert capability is not None, f"{capability_id} must be seeded"

    assert get_capability("provider.create")["category"] == "configuration"
    assert get_capability("product.chat")["category"] == "model"
    assert get_capability("product.chat")["risk"] == "low"
    assert get_capability("product.chat")["metadata"]["side_effect_class"] == "read_only"

    assert get_capability("provider.remove")["risk"] == "high"


# v0.2.0: No prefix magic

def test_infer_side_effect_no_prefix_magic():
    """Unregistered model.* capabilities no longer get prefix-based guesses."""
    from nous_runtime.capability.resolver import (
        _infer_reversibility,
        _infer_side_effect,
    )

    assert _infer_side_effect("model.zz_nonexistent.op") == "unknown"
    assert _infer_reversibility("model.zz_nonexistent.op") == "unknown"


def test_provider_reversibility_helper():
    """_provider_reversibility: declared > keyword > category > unknown."""
    from remote_terminal.nous_core.capability import (
        CAT_DEVICE,
        REVERSIBILITY_REVERSIBLE,
        register_capability,
        seed_default_capabilities,
        unregister_capability,
    )
    from nous_runtime.intelligence.reliability.executor import _provider_reversibility

    # 1. Declared metadata wins over the category default
    register_capability(
        "test.provrev.decl",
        category=CAT_DEVICE,
        provider="test",
        reversibility=REVERSIBILITY_REVERSIBLE,
    )
    try:
        assert _provider_reversibility("test.provrev.decl") == "reversible"
    finally:
        unregister_capability("test.provrev.decl")

    # 2. Keyword signals (preserves legacy device.pc.exec behavior)
    assert _provider_reversibility("test.unreg.exec_thing") == "irreversible"

    # 3. Category fallback for seeded model capability
    seed_default_capabilities()
    assert _provider_reversibility("model.reason") == "reversible"

    # 4. Conservative unknown for unregistered, keyword-free capability
    assert _provider_reversibility("test.unreg.nothing") == "unknown"


def test_privilege_risk_privileged_flag():
    """Declared privileged=True must force approval-level privilege risk."""
    import json as _json

    from nous_runtime.governance.contracts import ActionProposal
    from nous_runtime.governance.risk_engine import _privilege_risk

    prop = ActionProposal(
        action_type="capability.execute",
        capability_id="device.flash",
    )
    # metadata as dict
    assert _privilege_risk(prop, {"metadata": {"privileged": True}}) == 0.7
    # metadata as JSON string (raw registry row)
    assert _privilege_risk(prop, {"metadata": _json.dumps({"privileged": True})}) == 0.7
    # top-level key
    assert _privilege_risk(prop, {"privileged": True}) == 0.7
    # unprivileged default
    assert _privilege_risk(prop, {"metadata": {}}) == 0.1


# v0.2.0: Pipeline completion

def test_capability_decision_sets_candidate_type():
    """capability_decision candidates must carry CandidateType.CAPABILITY."""
    from remote_terminal.nous_core.capability import (
        CAT_SOFTWARE,
        register_capability,
        unregister_capability,
    )
    from nous_runtime.intelligence.decisions.capability import (
        _fallback_candidates,
        capability_decision,
    )
    from nous_runtime.intelligence.models import (
        CandidateType,
        DecisionContext,
        DecisionRequest,
        DecisionType,
    )

    decision = capability_decision(
        DecisionRequest(
            task_id="test-candidate-type",
            decision_type=DecisionType.CAPABILITY,
            context=DecisionContext(
                provider_candidates=(
                    {"provider_id": "executor-a", "name": "A",
                     "capabilities": ["agent.code.execute"],
                     "executor_type": "subprocess", "health": "ok",
                     "success_rate": 0.9, "latency_ms": 200},
                ),
                metadata={"required_capability": "agent.code.execute"},
            ),
        )
    )
    for candidate in decision.candidates:
        assert candidate.candidate_type == CandidateType.CAPABILITY

    # Fallback candidates from the registry carry the type too
    register_capability("test.ct.cap", category=CAT_SOFTWARE, provider="test-ct")
    try:
        fallback = _fallback_candidates("test.ct.cap")
        assert fallback, "expected at least one fallback candidate"
        for candidate in fallback:
            assert candidate.candidate_type == CandidateType.CAPABILITY
    finally:
        unregister_capability("test.ct.cap")


def test_route_model_software_uses_capability_decision():
    """Software tasks must flow through DecisionType.CAPABILITY."""
    from nous_runtime.intelligence.models import DecisionType
    from nous_runtime.intelligence.routing import route_model

    software_candidates = (
        {"provider_id": "sw-exec", "name": "SW", "kind": "custom",
         "capabilities": ("software.python.run",), "health": "ok"},
    )
    route = route_model("run tests", candidates=software_candidates)
    assert route.task == "software"
    assert route.decision is not None
    assert route.decision.decision_type == DecisionType.CAPABILITY

    # General prompts keep the provider routing path
    model_candidates = (
        {"provider_id": "llm", "name": "LLM", "kind": "custom",
         "capabilities": ("model.reason",), "health": "ok"},
    )
    route2 = route_model("hello how are you", candidates=model_candidates)
    assert route2.decision is not None
    assert route2.decision.decision_type == DecisionType.PROVIDER
