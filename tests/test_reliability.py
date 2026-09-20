"""Tests for P5.7 Provider Reliability and Circuit Control."""

from __future__ import annotations

import json
import math
import time
from tempfile import TemporaryDirectory

import pytest

from nous_runtime.intelligence.reliability.models import (
    NON_RETRYABLE_CATEGORIES,
    VALID_CIRCUIT_TRANSITIONS,
    CircuitConfig,
    CircuitState,
    CircuitStateRecord,
    FailureCategory,
    FailureSignal,
    FallbackExecution,
    ProviderExecutionResult,
    ProviderHealthSnapshot,
    RetryPolicy,
    snapshot_hash,
)
from nous_runtime.intelligence.reliability.classifier import classify_failure
from nous_runtime.intelligence.reliability.circuit_breaker import CircuitBreaker
from nous_runtime.intelligence.reliability.retry import RetryBudget, RetryController
from nous_runtime.intelligence.reliability.store import (
    InMemoryReliabilityStore,
    JsonlReliabilityStore,
)
from nous_runtime.intelligence.reliability.fault_injection import FaultInjector, FAULT_TYPES


# failure classification

class TestFailureClassification:
    def test_http_401_is_auth(self):
        signal = classify_failure(http_status=401)
        assert signal.category == FailureCategory.AUTHENTICATION
        assert not signal.retryable

    def test_http_429_is_rate_limit(self):
        signal = classify_failure(http_status=429)
        assert signal.category == FailureCategory.RATE_LIMIT
        assert signal.retryable

    def test_http_402_is_non_retryable_budget_failure(self):
        signal = classify_failure(http_status=402)
        assert signal.category == FailureCategory.BUDGET_EXCEEDED
        assert not signal.retryable

    def test_balance_error_code_is_non_retryable_budget_failure(self):
        signal = classify_failure(
            provider_error_code="NOUS_PROVIDER_BALANCE_EXHAUSTED"
        )
        assert signal.category == FailureCategory.BUDGET_EXCEEDED
        assert not signal.retryable

    def test_http_500_is_server_error(self):
        signal = classify_failure(http_status=500)
        assert signal.category == FailureCategory.SERVER_ERROR
        assert signal.retryable

    def test_http_503_is_server_error(self):
        signal = classify_failure(http_status=503)
        assert signal.category == FailureCategory.SERVER_ERROR

    def test_timeout_phase(self):
        signal = classify_failure(timeout_phase="connect")
        assert signal.category == FailureCategory.TIMEOUT

    def test_provider_error_code_auth(self):
        signal = classify_failure(provider_error_code="invalid_api_key")
        assert signal.category == FailureCategory.AUTHENTICATION

    def test_provider_error_code_rate_limit(self):
        signal = classify_failure(provider_error_code="rate_limit_exceeded")
        assert signal.category == FailureCategory.RATE_LIMIT

    def test_validation_failure(self):
        signal = classify_failure(response_validation_result=False)
        assert signal.category == FailureCategory.OUTPUT_VALIDATION
        assert not signal.retryable

    def test_unknown_is_conservative(self):
        signal = classify_failure()
        assert signal.category == FailureCategory.UNKNOWN
        assert signal.confidence <= 0.7

    def test_non_retryable_categories(self):
        for cat in NON_RETRYABLE_CATEGORIES:
            assert cat not in (FailureCategory.TIMEOUT, FailureCategory.CONNECTION, FailureCategory.SERVER_ERROR, FailureCategory.RATE_LIMIT)

    def test_auth_not_retryable(self):
        assert FailureCategory.AUTHENTICATION in NON_RETRYABLE_CATEGORIES
        assert FailureCategory.CANCELLED in NON_RETRYABLE_CATEGORIES

    def test_signal_roundtrip(self):
        signal = classify_failure(http_status=500, provider_id="p1", model_id="m1")
        data = signal.to_dict()
        restored = FailureSignal.from_dict(data)
        assert restored.category == FailureCategory.SERVER_ERROR
        assert restored.provider_id == "p1"


# circuit breaker

class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker("p:model")
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_traffic

    def test_consecutive_failures_open(self):
        cb = CircuitBreaker("p:m", CircuitConfig(consecutive_failure_threshold=3, min_sample_count=1))
        for _ in range(3):
            signal = classify_failure(http_status=500, provider_id="p")
            cb.record_failure(signal)
        assert cb.state == CircuitState.OPEN
        assert not cb.allows_traffic

    def test_cooldown_to_half_open(self):
        cb = CircuitBreaker("p:m", CircuitConfig(
            consecutive_failure_threshold=2,
            min_sample_count=1,
            cooldown_seconds=0.001,
        ))
        for _ in range(2):
            cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        assert cb.state == CircuitState.OPEN
        time.sleep(0.01)  # cooldown passes
        cb.record_success()  # triggers evaluation → HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_recovery(self):
        cb = CircuitBreaker("p:m", CircuitConfig(
            consecutive_failure_threshold=2,
            min_sample_count=1,
            cooldown_seconds=0.0,
            half_open_success_threshold=2,
        ))
        for _ in range(2):
            cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        cb.record_success()  # cooldown → HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("p:m", CircuitConfig(
            consecutive_failure_threshold=2, min_sample_count=1, cooldown_seconds=0.0,
        ))
        for _ in range(2):
            cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        cb.record_success()  # → HALF_OPEN
        cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        assert cb.state == CircuitState.OPEN

    def test_force_open(self):
        cb = CircuitBreaker("p:m")
        cb.force_open("maintenance")
        assert cb.state == CircuitState.FORCED_OPEN
        assert not cb.allows_traffic

    def test_force_open_only_clearable_by_close(self):
        cb = CircuitBreaker("p:m")
        cb.force_open("maintenance")
        # Successes should not change state
        cb.record_success()
        assert cb.state == CircuitState.FORCED_OPEN
        cb.force_close("maintenance done")
        assert cb.state == CircuitState.CLOSED

    def test_force_close_only_from_forced_open(self):
        cb = CircuitBreaker("p:m")
        with pytest.raises(ValueError):
            cb.force_close("not forced")

    def test_disabled_bypasses(self):
        cb = CircuitBreaker("p:m")
        cb.disable("testing")
        assert cb.state == CircuitState.DISABLED
        assert cb.allows_traffic
        for _ in range(10):
            cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        assert cb.state == CircuitState.DISABLED  # still disabled

    def test_enable_only_from_disabled(self):
        cb = CircuitBreaker("p:m")
        cb.disable("test")
        cb.enable("done")
        assert cb.state == CircuitState.CLOSED
        with pytest.raises(ValueError):
            cb.enable("bad")  # already CLOSED

    def test_illegal_transitions_rejected(self):
        cb = CircuitBreaker("p:m")
        with pytest.raises(ValueError):
            cb.half_open("bad")  # from CLOSED

    def test_sliding_window_prunes(self):
        cb = CircuitBreaker("p:m", CircuitConfig(sliding_window_size=1, consecutive_failure_threshold=100))
        for _ in range(5):
            cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        time.sleep(1.5)
        assert cb._window.total == 0  # pruned

    def test_snapshot(self):
        cb = CircuitBreaker("p:m")
        cb.record_success()
        snap = cb.snapshot()
        assert snap.provider_id == "p"
        assert snap.model_id == "m"
        assert snap.sample_count >= 1

    def test_history(self):
        cb = CircuitBreaker("p:m", CircuitConfig(consecutive_failure_threshold=1, min_sample_count=1))
        cb.record_failure(classify_failure(http_status=500, provider_id="p"))
        history = cb.get_history()
        assert len(history) >= 1
        assert history[-1].state == CircuitState.OPEN


# retry controller

class TestRetryController:
    def test_retry_success_on_first_attempt(self):
        ctrl = RetryController()
        budget = RetryBudget(max_attempts=3)
        result, attempts = ctrl.execute_with_retry(
            lambda: {"ok": True, "result": "success"},
            budget=budget,
        )
        assert result == {"ok": True, "result": "success"}
        assert len(attempts) == 1
        assert attempts[0].success

    def test_retry_on_transient_failure(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                return {"ok": False, "error": "server_error"}
            return {"ok": True, "result": "finally"}

        ctrl = RetryController()
        result, attempts = ctrl.execute_with_retry(flaky, budget=RetryBudget(max_attempts=5))
        assert result["ok"]
        assert len(attempts) >= 3

    def test_non_retryable_not_retried(self):
        call_count = [0]

        def auth_fail():
            call_count[0] += 1
            return {"ok": False, "error": "invalid_api_key"}

        ctrl = RetryController()
        result, attempts = ctrl.execute_with_retry(auth_fail, budget=RetryBudget(max_attempts=3))
        assert len(attempts) == 1
        assert call_count[0] == 1
        assert not attempts[0].success

    def test_budget_exhausted(self):
        call_count = [0]

        def always_fail():
            call_count[0] += 1
            return {"ok": False, "error": "timeout"}

        ctrl = RetryController()
        result, attempts = ctrl.execute_with_retry(always_fail, budget=RetryBudget(max_attempts=2))
        assert call_count[0] <= 2
        assert len(attempts) <= 2

    def test_exponential_backoff_increases(self):
        ctrl = RetryController()
        d1 = ctrl.compute_delay(1)
        d2 = ctrl.compute_delay(3)
        assert d2 > d1

    def test_retry_after_respected(self):
        ctrl = RetryController()
        delay = ctrl.compute_delay(1, retry_after_seconds=5.0)
        assert delay == 5.0

    def test_budget_tracks_attempts(self):
        budget = RetryBudget(max_attempts=3)
        assert not budget.exhausted
        budget.spent_attempts = 3
        assert budget.exhausted

    def test_non_idempotent_not_retried(self):
        ctrl = RetryController()
        # MALFORMED_RESPONSE is not safe to retry for non-idempotent operations
        signal = classify_failure(provider_error_code="malformed_response", provider_id="p")
        budget = RetryBudget(max_attempts=3)
        assert not ctrl.should_retry(signal, budget, is_idempotent=False, has_idempotency_key=False)

    def test_idempotent_is_retried(self):
        ctrl = RetryController()
        signal = classify_failure(http_status=500, provider_id="p")
        budget = RetryBudget(max_attempts=3)
        assert ctrl.should_retry(signal, budget, is_idempotent=True)


# reliability store

class TestReliabilityStore:
    def test_inmemory_store(self):
        store = InMemoryReliabilityStore()
        signal = classify_failure(http_status=500, provider_id="p")
        assert store.append_signal(signal)
        snapshot = ProviderHealthSnapshot(
            snapshot_id="s1", provider_id="p", status="degraded",
            circuit_state=CircuitState.OPEN, failure_count=5,
        )
        assert store.save_health_snapshot(snapshot)
        assert store.get_current_health("p") is not None

    def test_jsonl_store_signal(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            signal = classify_failure(http_status=500, provider_id="p")
            assert store.append_signal(signal)
            assert store.verify_integrity()["ok"]

    def test_jsonl_store_circuit_event(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            record = CircuitStateRecord(
                record_id="r1", breaker_key="p:m", state=CircuitState.OPEN,
                transition_reason="test",
            )
            assert store.append_circuit_event(record)
            restored = store.get_circuit_state("p:m")
            assert restored is not None
            assert restored.state == CircuitState.OPEN

    def test_jsonl_store_retry_attempt(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            from nous_runtime.intelligence.reliability.models import RetryAttempt
            attempt = RetryAttempt(attempt_id="a1", attempt_number=1, success=True)
            assert store.append_retry_attempt(attempt)

    def test_jsonl_store_fallback(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            fb = FallbackExecution(fallback_id="f1", depth=0, strategy="alternate_provider")
            assert store.append_fallback(fb)

    def test_jsonl_duplicate_prevention(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            signal = classify_failure(http_status=500, provider_id="p")
            assert store.append_signal(signal)
            assert not store.append_signal(signal)  # duplicate signal_id

    def test_truncated_jsonl_recovery(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            path = store.signals_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"signal_id": "ok"}\nbad line\n{"signal_id": "ok2"}\n', encoding="utf-8")
            result = store.verify_integrity()
            assert result["invalid_records"] >= 1

    def test_store_manifest_boundary(self):
        with TemporaryDirectory() as tmp:
            store = JsonlReliabilityStore(tmp)
            manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
            assert manifest["multi_host_safe"] is False
            assert "local" in manifest["supported_fs"]


# fault injection

class TestFaultInjection:
    def test_disabled_by_default(self):
        injector = FaultInjector()
        assert not injector.enabled

    def test_inject_rate_limit(self):
        injector = FaultInjector()
        injector.enable("rate_limit", provider_id="p")
        result = injector.inject("p", "m", "c")
        assert result is not None
        assert result["_fault_type"] == "rate_limit"
        assert result["http_status"] == 429

    def test_no_match_returns_none(self):
        injector = FaultInjector()
        injector.enable("rate_limit", provider_id="p")
        result = injector.inject("other", "m", "c")
        assert result is None

    def test_clear_all(self):
        injector = FaultInjector()
        injector.enable("timeout", provider_id="p")
        injector.clear_all()
        assert injector.inject("p", "m", "c") is None

    def test_probability_zero(self):
        injector = FaultInjector()
        injector.enable("http_500", provider_id="p", probability=0.0)
        result = injector.inject("p", "m", "c", _random=_MockRandom(0.0))
        assert result is None

    def test_probability_one(self):
        injector = FaultInjector()
        injector.enable("http_500", provider_id="p", probability=1.0)
        result = injector.inject("p", "m", "c", _random=_MockRandom(0.5))
        assert result is not None

    def test_globally_disabled(self):
        injector = FaultInjector()
        injector.enable("http_500", provider_id="p")
        injector.disable_globally()
        assert injector.inject("p", "m", "c") is None

    def test_all_fault_types_have_definitions(self):
        for ft in ["auth_failure", "rate_limit", "timeout", "connection_refused",
                    "http_500", "http_502", "http_503", "malformed_json",
                    "model_not_found", "cancellation"]:
            assert ft in FAULT_TYPES, f"Missing fault type: {ft}"


class _MockRandom:
    def __init__(self, value: float):
        self._value = value

    def random(self) -> float:
        return self._value


# models roundtrip

class TestModelRoundtrips:
    def test_execution_result_roundtrip(self):
        signal = classify_failure(http_status=500, provider_id="p")
        result = ProviderExecutionResult(
            execution_id="e1", success=False, provider_id="p",
            failure=signal, latency_ms=100.0, http_status=500,
        )
        data = result.to_dict()
        restored = ProviderExecutionResult.from_dict(data)
        assert restored.execution_id == "e1"
        assert restored.failure is not None
        assert restored.failure.category == FailureCategory.SERVER_ERROR

    def test_retry_policy_roundtrip(self):
        policy = RetryPolicy(policy_id="test", max_attempts=5)
        data = policy.to_dict()
        restored = RetryPolicy.from_dict(data)
        assert restored.policy_id == "test"
        assert restored.max_attempts == 5

    def test_fallback_execution_roundtrip(self):
        fb = FallbackExecution(
            fallback_id="fb1", depth=2, strategy="alternate_provider",
            lost_capabilities=("model.code",), privacy_changed=True,
        )
        data = fb.to_dict()
        restored = FallbackExecution.from_dict(data)
        assert restored.depth == 2
        assert "model.code" in restored.lost_capabilities
        assert restored.privacy_changed


# invariants

class TestInvariants:
    def test_no_nan_or_infinity(self):
        signal = classify_failure(http_status=500)
        for val in [signal.confidence]:
            assert math.isfinite(val)

    def test_snapshot_hash_stable(self):
        h1 = snapshot_hash({"a": 1})
        h2 = snapshot_hash({"a": 1})
        assert h1 == h2

    def test_legal_transitions_defined_for_all_states(self):
        for state in CircuitState:
            assert state in VALID_CIRCUIT_TRANSITIONS

    def test_forced_open_only_to_closed_or_disabled(self):
        transitions = VALID_CIRCUIT_TRANSITIONS[CircuitState.FORCED_OPEN]
        assert CircuitState.CLOSED in transitions
        assert CircuitState.DISABLED in transitions
        assert CircuitState.OPEN not in transitions
        assert CircuitState.HALF_OPEN not in transitions

    def test_signal_ids_are_deterministic(self):
        s1 = classify_failure(http_status=500, provider_id="p")
        s2 = classify_failure(http_status=500, provider_id="p")
        assert s1.signal_id == s2.signal_id
