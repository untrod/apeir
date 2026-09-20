import json
import math
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.intelligence import (
    CandidateType,
    DecisionCandidate,
    DecisionContext,
    DecisionRequest,
    DecisionType,
    JsonlDecisionStore,
    RuntimePolicyEngine,
    SchedulingRequest,
    SelectionContext,
    schedule_candidates,
    scheduling_request_from_dict,
    snapshot_hash,
)


def _candidate(candidate_id, **metadata):
    return DecisionCandidate(candidate_id=candidate_id, candidate_type=CandidateType.PROVIDER, metadata=metadata)


def _request(candidates, **constraints):
    return SchedulingRequest(
        request_id=snapshot_hash({"candidates": [c.candidate_id for c in candidates], "constraints": constraints}),
        candidates=tuple(candidates),
        context=SelectionContext(task_id="sched", decision_type=DecisionType.PROVIDER, constraints=constraints),
    )


def test_candidate_serialization_and_stable_hash():
    candidate = _candidate("local", capabilities=["model.reason"], success_rate=0.9)
    data = candidate.to_dict()
    restored = DecisionCandidate.from_dict(data)

    assert restored.candidate_id == candidate.candidate_id
    assert data["candidate_hash"] == candidate.to_dict()["candidate_hash"]
    assert data["candidate_type"] == "provider"


def test_candidate_order_independence_and_stable_tie_breaking():
    a = _candidate("a", success_rate=0.8, capabilities=["model.reason"], health="ok")
    b = _candidate("b", success_rate=0.8, capabilities=["model.reason"], health="ok")

    left = schedule_candidates(_request([b, a], required_capability="model.reason"))
    right = schedule_candidates(_request([a, b], required_capability="model.reason"))

    assert left.selected.selected_candidate_id == right.selected.selected_candidate_id == "a"


def test_hard_constraints_policy_denial_and_forced_safety_rejection():
    safe = _candidate("safe", capabilities=["model.reason"], health="ok")
    unsafe = _candidate("unsafe", capabilities=[], health="ok")

    denied = schedule_candidates(_request([safe, unsafe], required_capability="model.reason", deny_candidates=["safe"]))
    forced_unsafe = schedule_candidates(_request([safe, unsafe], required_capability="model.reason", force_candidate="unsafe"))

    assert denied.selected.selected_candidate_id != "safe"
    assert forced_unsafe.selected.selected_candidate_id == "safe"
    assert all(item.candidate_id != "unsafe" or item.reason_code == "required_capability" for item in forced_unsafe.rejected_candidates)


def test_hard_constraints_fail_closed_for_prefix_model_and_unknown_risk():
    prefix = _candidate("prefix", capabilities=["model"], health="ok")
    wildcard = _candidate("wildcard", capabilities=["model.*"], health="ok")
    missing_model = _candidate("missing-model", capabilities=["model.reason"], health="ok", risk="low")
    missing_risk = _candidate("missing-risk", capabilities=["model.reason"], health="ok", model="m1")

    prefix_result = schedule_candidates(_request([prefix], required_capability="model.reason"))
    wildcard_result = schedule_candidates(_request([wildcard], required_capability="model.reason"))
    model_result = schedule_candidates(_request([missing_model], allowed_models=["m1"]))
    risk_result = schedule_candidates(_request([missing_risk], risk_ceiling="low"))

    assert prefix_result.selected.no_safe_option is True
    assert wildcard_result.selected.selected_candidate_id == "wildcard"
    assert model_result.selected.no_safe_option is True
    assert risk_result.selected.no_safe_option is True

def test_unknown_and_stale_features_apply_uncertainty_penalty_without_nan():
    known = _candidate("known", success_rate=0.9, latency_ms=100, cost=0.1, quality=0.8, risk="low")
    unknown = _candidate("unknown", health="ok")
    stale = _candidate("stale", success_rate=0.9, latency_ms=100, cost=0.1, quality=0.8, risk="low", stale_features=["latency"])
    nan = _candidate("nan", success_rate=math.nan, latency_ms=math.inf)

    result = schedule_candidates(_request([unknown, known, stale, nan]))
    scores = {item.candidate.candidate_id: item.normalized_score for item in result.ranking.evaluations}

    assert scores["known"] > scores["unknown"]
    assert scores["known"] >= scores["stale"]
    assert all(math.isfinite(score) for score in scores.values())


def test_pareto_domination_and_unique_capability_preservation():
    strong = _candidate("strong", success_rate=0.95, quality=0.9, latency_ms=100, cost=0.1, risk="low", capabilities=["model.reason"])
    weak = _candidate("weak", success_rate=0.2, quality=0.2, latency_ms=3000, cost=0.9, risk="high", capabilities=["model.reason"])
    unique = _candidate("unique", success_rate=0.2, quality=0.2, latency_ms=3000, cost=0.9, risk="high", capabilities=["audio.transcribe"])

    result = schedule_candidates(_request([weak, unique, strong]))
    rejected = {item.candidate_id: item.reason_code for item in result.rejected_candidates}

    assert rejected["weak"] == "PARETO_DOMINATED"
    assert "unique" not in rejected


def test_no_safe_candidate_escalates():
    blocked = _candidate("blocked", capabilities=[], health="down")

    result = schedule_candidates(_request([blocked], required_capability="model.reason", availability_required=True))

    assert result.selected.no_safe_option is True
    assert result.selected.approval_required is True


def test_scheduler_request_from_dict_and_cli_simulate(tmp_path):
    request_data = {
        "request_id": "sim",
        "context": {"task_id": "sim", "decision_type": "provider", "constraints": {"required_capability": "model.reason"}},
        "candidates": [
            {"candidate_id": "p1", "candidate_type": "provider", "metadata": {"capabilities": ["model.reason"], "success_rate": 0.9}},
            {"candidate_id": "p2", "candidate_type": "provider", "metadata": {"capabilities": [], "success_rate": 1.0}},
        ],
    }
    request = scheduling_request_from_dict(request_data)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request_data), encoding="utf-8")
    result = CliRunner().invoke(app, ["decision", "simulate", "--input", str(path), "--json"])

    assert schedule_candidates(request).selected.selected_candidate_id == "p1"
    assert result.exit_code == 0
    assert json.loads(result.stdout)["selected"]["selected_candidate_id"] == "p1"


def test_decision_integrations_use_scheduler_metadata():
    retrieval = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="retrieval",
            decision_type=DecisionType.RETRIEVAL,
            context=DecisionContext(task_kind="question", retrieval_available=True, active_generation_id="gen"),
        )
    )
    provider = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="provider",
            decision_type=DecisionType.PROVIDER,
            context=DecisionContext(provider_candidates=({"provider_id": "p", "capabilities": ["model.reason"], "health": "ok"},)),
        )
    )
    recovery = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="recovery",
            decision_type=DecisionType.FALLBACK,
            context=DecisionContext(metadata={"error_category": "BACKEND"}),
        )
    )

    assert retrieval.candidates
    assert retrieval.outcome.metadata["scheduler_snapshot_hash"]
    assert provider.metadata["scheduler_snapshot_hash"]
    assert recovery.metadata["scheduler_snapshot_hash"]


def test_jsonl_store_concurrency_modes_and_file_lock(tmp_path):
    ws = tmp_path / ".nous"
    ws.mkdir()
    store = JsonlDecisionStore(ws, concurrency_mode="file_lock")
    decision = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="concurrency",
            decision_type=DecisionType.PROVIDER,
            context=DecisionContext(provider_candidates=({"provider_id": "p", "health": "ok"},)),
        )
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(store.persist_decision_snapshot, [decision] * 8))

    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    integrity = store.verify_integrity()
    single = JsonlDecisionStore(ws, concurrency_mode="single_process").concurrency_diagnostic()

    assert manifest["concurrency_mode"] == "file_lock"
    assert len(store.list_decisions()) == 1
    assert integrity["invalid_records"] == 0
    assert "SINGLE_PROCESS_MODE_NOT_MULTI_PROCESS_SAFE" in single["warnings"]
    with pytest.raises(ValueError):
        JsonlDecisionStore(ws, concurrency_mode="unsupported")


def _request_with_context(candidates, *, constraints, metadata):
    return SchedulingRequest(
        request_id=snapshot_hash(
            {
                "candidates": [candidate.candidate_id for candidate in candidates],
                "constraints": constraints,
                "metadata": metadata,
            }
        ),
        candidates=tuple(candidates),
        context=SelectionContext(
            task_id="sched-v2",
            decision_type=DecisionType.PROVIDER,
            constraints=constraints,
            metadata=metadata,
        ),
    )


def test_scheduler_v2_fail_closed_feasibility_constraints():
    constraints = {
        "required_capability": "model.reason",
        "workspace_permission": "write",
        "privacy": "private",
        "locality": "local",
        "allowed_models": ["m1"],
        "risk_ceiling": "medium",
        "node_online_required": True,
        "required_resources": {"cpu": 2, "memory": 4},
        "provider_circuit_required_closed": True,
        "provider_rate_limit_required": True,
        "resource_budget": {"cost": 1.0},
        "required_approval_state": "approved",
    }
    good = _candidate(
        "good",
        capabilities=["model.reason"],
        workspace_permissions=["write"],
        privacy="private",
        locality="local",
        model="m1",
        risk="low",
        node_online=True,
        available_resources={"cpu": 8, "memory": 16},
        circuit_state="closed",
        rate_limit_state="ok",
        resource_usage={"cost": 0.2},
        approval_state="approved",
    )
    blocked = _candidate("blocked", capabilities=["model.reason"], health="ok")

    result = schedule_candidates(
        _request_with_context([blocked, good], constraints=constraints, metadata={"approval_state": "approved"})
    )
    blocked_failures = {
        item.constraint
        for item in result.constraint_trace
        if not item.passed
    }

    assert result.selected.selected_candidate_id == "good"
    assert {
        "workspace_permission",
        "privacy",
        "locality",
        "allowed_models",
        "risk_ceiling",
        "node_online",
        "node_capacity.cpu",
        "provider_circuit",
        "provider_rate_limit",
        "resource_budget.cost",
    } <= blocked_failures


def test_scheduler_v2_fairness_reservation_and_deterministic_aging():
    candidate = _candidate("worker", available_worker_slots=1, workflow_active_workers=0)
    reserved = schedule_candidates(
        _request_with_context(
            [candidate],
            constraints={"priority_class": "P4", "interactive_capacity_reservation": 1},
            metadata={},
        )
    )
    aged = schedule_candidates(
        _request_with_context(
            [candidate],
            constraints={"priority_class": "P5", "aging_seconds_per_class": 300},
            metadata={"queued_seconds": 1200},
        )
    )
    user_limited = schedule_candidates(
        _request_with_context(
            [candidate],
            constraints={"per_user_concurrency_limit": 2},
            metadata={"active_user_runs": 2},
        )
    )

    assert reserved.selected.no_safe_option is True
    assert aged.trace["effective_priority"] == "P1"
    assert aged.selected.selected_candidate_id == "worker"
    assert user_limited.selected.no_safe_option is True


def test_scheduler_v2_resource_score_and_complete_explanation():
    fast = _candidate("fast", resource_fit=0.9, network_rtt_ms=20, node_queue_depth=1, provider_failure_rate=0.01)
    slow = _candidate("slow", resource_fit=0.6, network_rtt_ms=900, node_queue_depth=50, provider_failure_rate=0.3)

    result = schedule_candidates(_request([slow, fast]))
    explanation = result.trace["explanation"]

    assert result.selected.selected_candidate_id == "fast"
    assert explanation["candidates_considered"] == ["fast", "slow"]
    assert explanation["selected_candidate"] == "fast"
    assert "resource_fit" in explanation["normalized_score_components"]["fast"]
    assert explanation["fallback_order"] == list(result.selected.fallback_candidates)
