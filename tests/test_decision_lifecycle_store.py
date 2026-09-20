import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

import nous_runtime.intelligence.store as store_module
from nous_runtime.cli.main import app
from nous_runtime.intelligence import (
    DecisionContext,
    DecisionRequest,
    DecisionStatus,
    DecisionType,
    InMemoryDecisionStore,
    JsonlDecisionStore,
    OutcomeError,
    RuntimePolicyEngine,
    VALID_DECISION_TRANSITIONS,
    build_assessment,
    lifecycle_for_workspace,
    record_provider_outcome,
    record_recovery_outcome,
    record_retrieval_outcome,
    sanitize_mapping,
    validate_status_transition,
)
from nous_runtime.intelligence.lifecycle import DecisionLifecycleService


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    ws.mkdir()
    (ws / "project.json").write_text(json.dumps({"name": "lifecycle-test"}), encoding="utf-8")
    return ws


def _decision():
    request = DecisionRequest(
        task_id="task_lifecycle",
        decision_type=DecisionType.PROVIDER,
        context=DecisionContext(
            provider_candidates=(
                {
                    "provider_id": "local",
                    "health": "ok",
                    "capabilities": ["model.reason"],
                    "required_capability": "model.reason",
                },
            )
        ),
    )
    return RuntimePolicyEngine().decide(request)


def test_lifecycle_valid_and_invalid_transitions():
    store = InMemoryDecisionStore()
    service = DecisionLifecycleService(store)
    decision = _decision()

    service.record_decision_created(decision)
    service.record_execution_start(decision, execution_id="exec_1")
    outcome = service.record_execution_completion(decision, execution_id="exec_1", status=DecisionStatus.SUCCEEDED)
    assessment = build_assessment(outcome, execution_success=True, task_success=True)
    service.add_assessment(assessment)
    service.close_decision(decision.decision_id)

    assert service.current_status(decision.decision_id) == DecisionStatus.CLOSED
    with pytest.raises(ValueError):
        decision.transition(DecisionStatus.RUNNING)


def test_lifecycle_transition_table_is_enforced():
    for current, targets in VALID_DECISION_TRANSITIONS.items():
        for target in targets:
            validate_status_transition(current, target)

    statuses = list(DecisionStatus)
    for current in statuses:
        for target in statuses:
            if current == target or target in VALID_DECISION_TRANSITIONS[current]:
                continue
            with pytest.raises(ValueError):
                validate_status_transition(current, target)


def test_outcome_roundtrip_idempotency_and_redaction(tmp_path):
    ws = _workspace(tmp_path)
    store = JsonlDecisionStore(ws)
    service = DecisionLifecycleService(store)
    decision = _decision()

    service.record_decision_created(decision)
    outcome1 = service.record_execution_completion(
        decision,
        execution_id="exec_sensitive",
        status=DecisionStatus.FAILED,
        metadata={"api_key": "placeholder-value", "latency_ms": 12},
        error=OutcomeError("AUTH", error_code="NOUS_AUTHENTICATION_FAILED", message="authentication failed"),
    )
    outcome2 = service.record_execution_completion(
        decision,
        execution_id="exec_sensitive",
        status=DecisionStatus.FAILED,
        metadata={"api_key": "placeholder-value", "latency_ms": 12},
    )

    assert outcome1.outcome_id == outcome2.outcome_id
    assert len(store.list_outcomes()) == 1
    stored = store.read_outcome(outcome1.outcome_id)
    assert stored is not None
    assert stored.metadata["api_key"] == "[redacted]"
    assert stored.error is not None
    assert stored.error.message == "authentication failed"


def test_retrieval_provider_recovery_outcome_helpers(tmp_path):
    ws = _workspace(tmp_path)
    service = lifecycle_for_workspace(str(ws))

    retrieval_decision = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="retrieval_task",
            decision_type=DecisionType.RETRIEVAL,
            context=DecisionContext(task_kind="question", retrieval_available=True, active_generation_id="gen_1"),
        )
    )
    provider_decision = _decision()
    recovery_decision = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="recovery_task",
            decision_type=DecisionType.FALLBACK,
            context=DecisionContext(metadata={"error_category": "BACKEND"}),
        )
    )

    retrieval = record_retrieval_outcome(service, retrieval_decision, execution_id="retr_exec", result_count=3, latency_ms=5)
    provider = record_provider_outcome(service, provider_decision, execution_id="prov_exec", ok=True, token_usage={"input": 10})
    recovery = record_recovery_outcome(service, recovery_decision, execution_id="rec_exec", recovered=True)

    assert retrieval.metadata["result_count"] == 3
    assert provider.token_usage["input"] == 10
    assert recovery.status == DecisionStatus.SUCCEEDED


def test_jsonl_store_recovers_truncated_line_and_detects_incomplete(tmp_path):
    ws = _workspace(tmp_path)
    store = JsonlDecisionStore(ws)
    service = DecisionLifecycleService(store)
    decision = _decision()
    service.record_decision_created(decision)
    store.events_path.parent.mkdir(parents=True, exist_ok=True)
    with store.events_path.open("a", encoding="utf-8") as fh:
        fh.write("{not-json\n")

    integrity = store.verify_integrity()
    incomplete = service.incomplete_decisions()

    assert integrity["invalid_records"] == 1
    assert incomplete[0].decision_id == decision.decision_id


def test_find_incomplete_decisions_reads_each_stream_once(
    tmp_path,
    monkeypatch,
):
    ws = _workspace(tmp_path)
    store = JsonlDecisionStore(ws)
    service = DecisionLifecycleService(store)
    for index in range(3):
        decision = RuntimePolicyEngine().decide(
            DecisionRequest(
                task_id=f"task_{index}",
                decision_type=DecisionType.PROVIDER,
                context=DecisionContext(
                    provider_candidates=(
                        {"provider_id": f"p{index}", "health": "ok"},
                    )
                ),
            )
        )
        service.record_decision_created(decision)

    reads: dict[str, int] = {}
    original = store_module._read_jsonl

    def counted(path):
        reads[path.name] = reads.get(path.name, 0) + 1
        return original(path)

    monkeypatch.setattr(store_module, "_read_jsonl", counted)

    incomplete = store.find_incomplete_decisions()

    assert len(incomplete) == 3
    assert reads["snapshots.jsonl"] == 1
    assert reads["events.jsonl"] == 1


def test_jsonl_store_concurrent_append_and_rebuild(tmp_path):
    ws = _workspace(tmp_path)
    store = JsonlDecisionStore(ws)
    decisions = []
    for idx in range(10):
        request = DecisionRequest(
            task_id=f"task_{idx}",
            decision_type=DecisionType.PROVIDER,
            context=DecisionContext(provider_candidates=({"provider_id": f"p{idx}", "health": "ok"},)),
        )
        decisions.append(RuntimePolicyEngine().decide(request))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(store.persist_decision_snapshot, decisions))

    rebuilt = store.rebuild_indexes()

    assert len(store.list_decisions(limit=20)) == 10
    assert rebuilt["decisions"] == 10


def test_decision_cli_outcomes_timeline_incomplete_and_store(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    service = lifecycle_for_workspace(str(ws))
    decision = _decision()
    service.record_decision_created(decision)
    outcome = service.record_execution_completion(decision, execution_id="exec_cli", status=DecisionStatus.SUCCEEDED)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    outcomes = runner.invoke(app, ["decision", "outcomes", "--json"])
    outcome_show = runner.invoke(app, ["decision", "outcome", outcome.outcome_id, "--json"])
    timeline = runner.invoke(app, ["decision", "timeline", decision.decision_id, "--json"])
    assess = runner.invoke(app, ["decision", "assess", outcome.outcome_id, "--execution-success", "--json"])
    stats = runner.invoke(app, ["decision", "store", "stats", "--json"])
    verify = runner.invoke(app, ["decision", "store", "verify", "--json"])

    assert outcomes.exit_code == 0
    assert outcome_show.exit_code == 0
    assert timeline.exit_code == 0
    assert assess.exit_code == 0
    assert stats.exit_code == 0
    assert verify.exit_code == 0
    assert json.loads(outcome_show.stdout)["outcome_id"] == outcome.outcome_id
    assert json.loads(stats.stdout)["outcomes"] == 1


def test_pipeline_records_retrieval_outcome_when_workspace_exists(tmp_path, monkeypatch):
    from nous_runtime.planner.pipeline import DecisionPipeline

    ws = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = DecisionPipeline().run("summarize project", auto_execute=False)
    store = JsonlDecisionStore(ws)
    outcomes = store.list_outcomes(limit=10)

    assert result.decisions
    assert outcomes
    assert outcomes[-1].decision_id == result.decisions[0].decision_id


def test_sanitize_mapping_redacts_sensitive_fields():
    data = sanitize_mapping({"nested": {"authorization": "Bearer value"}, "safe": "ok"})

    assert data["nested"]["authorization"] == "[redacted]"
    assert data["safe"] == "ok"
