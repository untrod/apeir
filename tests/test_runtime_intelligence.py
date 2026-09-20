import json

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.intelligence import (
    DECISION_SCHEMA_VERSION,
    DecisionContext,
    DecisionHistory,
    DecisionRecord,
    DecisionRequest,
    DecisionStatus,
    DecisionType,
    RuntimePolicyEngine,
    migrate_record,
)
from nous_runtime.intelligence.decisions.recovery import ErrorCategory
from nous_runtime.intelligence.policies import CompositePolicy, FallbackPolicy, OverridePolicy, RulePolicy, StaticPolicy
from nous_runtime.intelligence.registry import PolicyRegistry


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    ws.mkdir()
    (ws / "project.json").write_text(json.dumps({"name": "p5-test"}), encoding="utf-8")
    return ws


def _request(decision_type=DecisionType.RETRIEVAL, **kwargs):
    context = DecisionContext(**kwargs)
    return DecisionRequest(task_id="task_1", decision_type=decision_type, context=context)


def test_decision_contract_serializes_and_replays(tmp_path):
    ws = _workspace(tmp_path)
    history = DecisionHistory(ws)
    request = _request(
        task_kind="question",
        prompt="read project docs",
        retrieval_available=True,
        active_generation_id="gen_1",
    )

    decision = RuntimePolicyEngine().decide(request)
    history.append(decision)
    replayed = history.replay(decision.decision_id)

    assert decision.decision_id == replayed.decision_id
    assert decision.selected == "enabled"
    assert replayed.outcome.metadata["generation_id"] == "gen_1"
    data = decision.to_dict()
    assert data["schema_version"] == DECISION_SCHEMA_VERSION
    assert data["runtime_version"]
    assert data["decision_status"] == DecisionStatus.SELECTED.value
    assert DecisionRecord.from_dict(data).record_id == decision.decision_id


def test_decision_status_transitions_and_migration():
    request = _request(task_kind="question")
    decision = RuntimePolicyEngine().decide(request)

    assert decision.transition(DecisionStatus.DISPATCHED).status == DecisionStatus.DISPATCHED
    with pytest.raises(ValueError):
        decision.transition(DecisionStatus.PROPOSED)

    old = {"decision_id": "d1", "task_id": "t1", "decision_type": "retrieval", "selected": "enabled"}
    migrated = migrate_record(old, "0.1")
    assert migrated["schema_version"] == DECISION_SCHEMA_VERSION
    assert migrated["decision_status"] == DecisionStatus.SELECTED.value


def test_rule_policy_uses_restricted_structured_conditions():
    policy = RulePolicy(
        policy_id="test.rule",
        version="1.0",
        decision_type="retrieval",
        priority=10,
        conditions=({"field": "context.task_kind", "operator": "in", "value": ["research"]},),
        action={"selected": "enabled", "confidence": 0.7},
    )
    request = _request(task_kind="research")

    assert policy.matches(request) is True
    assert policy.decide(request).selected == "enabled"

    blocked = RulePolicy(
        policy_id="bad.rule",
        version="1.0",
        decision_type="retrieval",
        priority=10,
        conditions=({"field": "context.task_kind", "operator": "eval", "value": "research"},),
        action={"selected": "enabled"},
    )
    with pytest.raises(ValueError):
        blocked.matches(request)

    nested = RulePolicy(
        policy_id="nested.rule",
        version="1.0",
        decision_type="retrieval",
        priority=10,
        conditions=(
            {
                "operator": "and",
                "conditions": [
                    {"field": "context.task_kind", "operator": "ne", "value": "simple"},
                    {"field": "context.task_kind", "operator": "not_in", "value": ["format"]},
                ],
            },
        ),
        action={"selected": "enabled"},
    )
    assert nested.matches(request) is True


def test_policy_registry_priority_and_policy_types():
    request = _request(task_kind="question")
    low = StaticPolicy("low", "1.0", "retrieval", "disabled", priority=1)
    high = StaticPolicy("high", "1.0", "retrieval", "enabled", priority=10)
    registry = PolicyRegistry()
    registry.register(low)
    registry.register(high)

    assert registry.resolve(request)[0].policy_id == "high"

    override = OverridePolicy("override", "1.0", "retrieval", "retrieval")
    override_request = _request(explicit_overrides={"retrieval": "disabled"})
    assert override.matches(override_request) is True
    assert override.decide(override_request).selected == "disabled"

    composite = CompositePolicy("composite", "1.0", "retrieval", (low, high), mode="highest_priority")
    fallback = FallbackPolicy("fallback", "1.0", "retrieval", high, "disabled")
    assert composite.decide(request).policy_id == "composite"
    assert fallback.decide(request).policy_id == "fallback"


def test_workspace_policy_loader_and_engine_layering(tmp_path):
    ws = _workspace(tmp_path)
    policies = ws / "policies"
    policies.mkdir()
    (policies / "retrieval.yaml").write_text(
        """
policies:
  - policy_id: workspace.retrieval.docs
    policy_type: rule
    decision_type: retrieval
    version: "1.0"
    source: workspace
    priority: 50
    conditions:
      - field: context.task_kind
        operator: eq
        value: question
    actions:
      selected: enabled
      confidence: 0.88
""",
        encoding="utf-8",
    )
    from nous_runtime.intelligence.policy_loader import load_workspace_policies

    loaded = load_workspace_policies(ws)
    request = _request(task_kind="question")
    decision = RuntimePolicyEngine.from_workspace(str(ws)).decide(request)

    assert not loaded.diagnostics
    assert loaded.specs[0].policy_hash
    assert decision.policy_id == "workspace.retrieval.docs"
    assert decision.policy_hashes["workspace.retrieval.docs"] == loaded.specs[0].policy_hash


def test_provider_routing_scores_contextual_candidates():
    request = _request(
        decision_type=DecisionType.PROVIDER,
        provider_candidates=(
            {
                "provider_id": "remote",
                "capabilities": ["model.reason"],
                "required_capability": "model.reason",
                "health": "degraded",
                "success_rate": 0.5,
            },
            {
                "provider_id": "ollama-local",
                "capabilities": ["model.reason"],
                "required_capability": "model.reason",
                "health": "ok",
                "success_rate": 0.9,
                "latency_ms": 300,
            },
        ),
    )

    decision = RuntimePolicyEngine().decide(request)

    assert decision.selected == "ollama-local"
    assert decision.outcome.metadata["fallback_chain"] == ["remote"]


def test_recovery_policy_classifies_error_categories():
    timeout = _request(decision_type=DecisionType.RETRY, metadata={"error_category": ErrorCategory.TIMEOUT.value})
    auth = _request(decision_type=DecisionType.RETRY, metadata={"error_category": ErrorCategory.AUTH.value})
    backend = _request(decision_type=DecisionType.FALLBACK, metadata={"error_category": ErrorCategory.BACKEND.value})

    engine = RuntimePolicyEngine()

    assert engine.decide(timeout).selected == "retry_once"
    assert engine.decide(auth).selected == "stop"
    assert engine.decide(backend).selected == "fallback"


def test_decision_pipeline_exposes_runtime_decisions():
    from nous_runtime.planner.pipeline import DecisionPipeline

    result = DecisionPipeline().run(
        "review project docs",
        constraints={"retrieval_available": True, "active_generation_id": "gen_1"},
        auto_execute=False,
    )

    assert result.decisions[0].selected == "enabled"
    assert result.plan is not None
    assert result.plan.metadata["runtime_decisions"][0]["decision_id"] == result.decisions[0].decision_id


def test_decision_cli_records_lists_explains_and_replays(tmp_path, monkeypatch):
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "decision",
            "test",
            "retrieval",
            "--prompt",
            "read project docs",
            "--retrieval-available",
            "--active-generation-id",
            "gen_1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    decision_id = json.loads(result.stdout)["decision_id"]

    listed = runner.invoke(app, ["decision", "list", "--json"])
    explained = runner.invoke(app, ["decision", "explain", decision_id])
    replayed = runner.invoke(app, ["decision", "replay", decision_id, "--json"])
    inspected = runner.invoke(app, ["inspect", "decisions", "--json"])
    from nous_runtime.api.routes import route

    api_result = route("GET", "/api/inspector/decisions")

    assert listed.exit_code == 0
    assert explained.exit_code == 0
    assert replayed.exit_code == 0
    assert inspected.exit_code == 0
    assert json.loads(replayed.stdout)["decision_id"] == decision_id
    assert json.loads(inspected.stdout)[0]["decision_id"] == decision_id
    assert api_result["ok"] is True
    assert api_result["data"][0]["decision_id"] == decision_id


def test_policy_cli_lists_validates_resolves_and_tests(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    policies = ws / "policies"
    policies.mkdir()
    policy_file = policies / "provider-routing.yaml"
    policy_file.write_text(
        """
policies:
  - policy_id: workspace.provider.default
    policy_type: static
    decision_type: provider
    source: workspace
    priority: 10
    actions:
      selected: local
      confidence: 0.6
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    listed = runner.invoke(app, ["policy", "list", "--json"])
    validated = runner.invoke(app, ["policy", "validate", "--json"])
    shown = runner.invoke(app, ["policy", "show", "workspace.provider.default", "--json"])
    resolved = runner.invoke(app, ["policy", "resolve", "provider", "--json"])
    tested = runner.invoke(
        app,
        [
            "policy",
            "test",
            "workspace.provider.default",
            "--input",
            json.dumps({"task_id": "t1", "decision_type": "provider", "context": {}}),
            "--json",
        ],
    )

    assert listed.exit_code == 0
    assert validated.exit_code == 0
    assert shown.exit_code == 0
    assert resolved.exit_code == 0
    assert tested.exit_code == 0
    assert json.loads(listed.stdout)["policies"][0]["policy_hash"]
    assert json.loads(validated.stdout)["valid"] is True
    assert json.loads(shown.stdout)["policy_id"] == "workspace.provider.default"
    assert json.loads(resolved.stdout)[0]["policy_id"] == "workspace.provider.default"
    assert json.loads(tested.stdout)["decision"]["selected"] == "local"
