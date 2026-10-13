"""Usage evidence distinguishes reported values, estimates and uncertainty."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
import json
from threading import Barrier
import uuid

import pytest

from nous_runtime.model_runtime.cost_control import (
    CostController,
    CostLimitExceeded,
    CostPolicy,
    Pricing,
    PricingCatalog,
    Usage,
)
from nous_runtime.model_runtime.models import ModelRequest, ModelResponse
from nous_runtime.core.redaction import register_sensitive_value


def controller(tmp_path, *, price=True, **limits):
    return CostController(
        tmp_path / "usage.sqlite3",
        policy=CostPolicy(**limits),
        pricing=PricingCatalog({"provider/model": Pricing(1, 2, 0.25, 1.25)})
        if price
        else PricingCatalog(),
    )


def authorize(value, *, attempt=1, **metadata):
    return value.authorize(
        ModelRequest(
            task_id="original-task",
            messages=({"role": "user", "content": "original"},),
            metadata={"estimated_input_tokens": 100, "max_tokens": 8, **metadata},
        ),
        provider_id="provider",
        model_id="model",
        attempt=attempt,
    )


def response(reservation, usage=None, **kwargs):
    return ModelResponse(
        request_id=reservation.request.request_id,
        model_id="model",
        instance_id="instance",
        usage=usage or {},
        **kwargs,
    )


def test_missing_usage_is_unknown_not_reported_zero():
    value = Usage.from_mapping({}).to_dict()
    assert all(value[name] is None for name in value["counter_measurements"])
    assert set(value["counter_measurements"].values()) == {"unknown"}


def test_reported_zero_has_presence_and_does_not_select_an_alias():
    value = Usage.from_mapping(
        {
            "input_tokens": 0,
            "prompt_tokens": 8,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
    ).to_dict()
    assert value["input_tokens"] == value["output_tokens"] == value["total_tokens"] == 0
    assert value["counter_measurements"]["input_tokens"] == "reported"
    assert value["cache_creation_input_tokens"] is None


@pytest.mark.parametrize(
    "value", [True, 2.5, -1, float("nan"), float("inf"), "not-a-counter"]
)
def test_malformed_usage_cannot_be_coerced_into_evidence(value):
    with pytest.raises(CostLimitExceeded):
        Usage.from_mapping({"input_tokens": value})


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 3, "cached_input_tokens": 4},
        {"output_tokens": 1, "reasoning_tokens": 2},
        {"input_tokens": 5, "output_tokens": 3, "total_tokens": 0},
        {"input_tokens": 5, "cached_input_tokens": 2, "cache_miss_input_tokens": 0},
    ],
)
def test_contradictory_usage_is_not_silently_repaired(usage):
    with pytest.raises(CostLimitExceeded):
        Usage.from_mapping(usage)


def test_anthropic_split_counts_normalize_once_with_cache_creation():
    raw = {
        "input_tokens": 5,
        "output_tokens": 2,
        "cache_read_input_tokens": 7,
        "cache_creation_input_tokens": 3,
    }
    value = Usage.from_mapping(raw)
    assert value.input_tokens == 15
    assert value.cache_creation_input_tokens == 3
    assert value.reasoning_tokens is None
    assert Usage.from_mapping(value.to_dict()).to_dict() == value.to_dict()


def test_missing_anthropic_component_does_not_claim_complete_input():
    value = Usage.from_mapping(
        {"input_tokens": 5, "output_tokens": 2, "cache_read_input_tokens": 7}
    )
    assert value.cached_input_tokens == 7
    assert value.input_tokens is None and value.total_tokens is None


def test_unknown_pricing_blocks_enforced_usd_budget(tmp_path):
    value = controller(tmp_path, price=False)
    with pytest.raises(CostLimitExceeded, match="pricing"):
        authorize(value)
    assert value.summary()["reservations"] == []


def test_explicit_zero_pricing_remains_valid(tmp_path):
    value = CostController(
        tmp_path / "usage.sqlite3",
        pricing=PricingCatalog({"provider/model": Pricing(0, 0, 0, 0)}),
    )
    reservation = authorize(value)
    assert reservation.estimated_cost_usd == 0


def test_token_only_unpriced_call_retains_unknown_billing(tmp_path):
    value = controller(
        tmp_path, price=False, max_daily_cost_usd=None, max_retry_cost_usd=None
    )
    reservation = authorize(value)
    normalized, receipt = value.commit(reservation, response(reservation))
    assert (
        receipt["cost_usd"] is None
        and normalized.metadata["cost_measurement"] == "unknown"
    )
    assert receipt["usage"]["total_tokens"] is None
    assert value.summary()["total_cost_usd"] is None
    assert value.summary()["reserved_tokens"] == 108


@pytest.mark.parametrize("price", [-1, True, float("nan"), float("inf"), "not-a-price"])
def test_invalid_rates_fail_closed(price):
    with pytest.raises(CostLimitExceeded):
        Pricing(price, 1, 1)


def test_empty_price_entry_is_unknown():
    assert Pricing().estimate(Usage(input_tokens=0, output_tokens=0)) is None


def test_reported_zero_cost_is_not_replaced_by_price_estimate(tmp_path):
    value = controller(tmp_path)
    reservation = authorize(value)
    normalized, receipt = value.commit(
        reservation,
        response(
            reservation,
            {"input_tokens": 3, "output_tokens": 2},
            metadata={"cost_measurement": "reported"},
        ),
    )
    assert normalized.cost_usd == receipt["cost_usd"] == 0
    assert receipt["cost_measurement"] == "reported"


def test_default_zero_cost_is_only_a_price_estimate(tmp_path):
    value = controller(tmp_path)
    reservation = authorize(value)
    _, receipt = value.commit(
        reservation, response(reservation, {"input_tokens": 3, "output_tokens": 2})
    )
    assert receipt["cost_usd"] == pytest.approx(0.000007)
    assert receipt["cost_measurement"] == "estimated"


def test_billable_failure_is_durable_and_keeps_retry_exposure(tmp_path):
    value = controller(tmp_path, max_daily_tokens=200)
    reservation = authorize(value)
    value.fail(reservation, reason="FAKE-PRIVATE-PROVIDER-ERROR", dispatched=True)
    reopened = controller(tmp_path, max_daily_tokens=200)
    summary = reopened.summary()
    assert summary["total_tokens"] is None and summary["total_cost_usd"] is None
    assert summary["uncertain_calls"] == 1 and summary["reserved_tokens"] == 108
    assert summary["remaining"]["tokens"] == 92
    assert "FAKE-PRIVATE-PROVIDER-ERROR" not in str(summary)
    with pytest.raises(CostLimitExceeded, match="daily model token"):
        authorize(reopened, attempt=2)
    reopened.fail(reservation, reason="repeated failure", dispatched=True)
    assert reopened.summary()["requests"] == 1


def test_confirmed_predispatch_failure_releases_only_its_reservation(tmp_path):
    value = controller(tmp_path)
    reservation = authorize(value)
    value.fail(reservation, reason="setup denied", dispatched=False)
    assert value.summary()["reserved_tokens"] == 0
    assert value.summary()["receipts"][0]["status"] == "not_dispatched"
    assert value.summary()["total_tokens"] == 0


def test_malformed_provider_usage_is_preserved_as_billing_uncertainty(tmp_path):
    value = controller(tmp_path)
    reservation = authorize(value)
    with pytest.raises(CostLimitExceeded, match="billing remains uncertain"):
        value.commit(reservation, response(reservation, {"input_tokens": True}))
    assert value.summary()["uncertain_calls"] == 1
    assert value.summary()["reserved_tokens"] == 108


def test_original_late_usage_reconciles_without_a_new_call(tmp_path):
    value = controller(tmp_path)
    reservation = authorize(value)
    value.fail(reservation, reason="lost response")
    normalized, receipt = value.commit(
        reservation, response(reservation, {"input_tokens": 3, "output_tokens": 2})
    )
    assert value.summary()["requests"] == 1 and value.summary()["reserved_tokens"] == 0
    assert receipt["status"] == "completed"
    assert (
        value.commit(reservation, normalized)[1]["receipt_id"] == receipt["receipt_id"]
    )
    with pytest.raises(CostLimitExceeded, match="cannot change"):
        value.commit(
            reservation, response(reservation, {"input_tokens": 3, "output_tokens": 3})
        )


def test_multiple_iterations_preserve_cache_and_reasoning_after_restart(tmp_path):
    value = controller(tmp_path)
    first = authorize(value)
    value.commit(
        first,
        response(
            first,
            {
                "input_tokens": 10,
                "output_tokens": 3,
                "cached_input_tokens": 6,
                "cache_creation_input_tokens": 0,
                "reasoning_tokens": 2,
            },
        ),
    )
    second = authorize(value)
    value.commit(
        second,
        response(
            second,
            {
                "input_tokens": 5,
                "output_tokens": 2,
                "cache_read_input_tokens": 7,
                "cache_creation_input_tokens": 3,
                "reasoning_tokens": 0,
            },
        ),
    )
    summary = controller(tmp_path).summary()
    assert summary["input_tokens"] == 25 and summary["output_tokens"] == 5
    assert summary["total_tokens"] == 30 and summary["reasoning_tokens"] == 2
    assert (
        summary["cached_input_tokens"] == 13
        and summary["cache_creation_input_tokens"] == 3
    )
    assert summary["cache_miss_input_tokens"] == 12
    assert summary["total_cost_usd"] == pytest.approx(0.000026)
    assert summary["cost_measurement"] == "estimated"
    assert {receipt["request_id"] for receipt in summary["receipts"]} == {
        first.request.request_id,
        second.request.request_id,
    }


def test_independent_controllers_cannot_overbook_one_budget(tmp_path):
    values = [
        controller(tmp_path, max_daily_tokens=108),
        controller(tmp_path, max_daily_tokens=108),
    ]
    ready = Barrier(2)

    def reserve(value):
        ready.wait(timeout=5)
        try:
            return authorize(value)
        except CostLimitExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(reserve, values))
    assert sum(reservation is not None for reservation in reservations) == 1
    assert len(values[0].summary()["reservations"]) == 1


def test_unfinished_reservation_never_appears_as_zero_usage_after_restart(tmp_path):
    value = controller(tmp_path)
    authorize(value)
    summary = controller(tmp_path).summary()
    assert summary["total_tokens"] is None and summary["total_cost_usd"] is None
    assert summary["pending_requests"] == 1 and summary["reserved_tokens"] == 108


def test_priced_failed_call_keeps_enforced_usd_exposure(tmp_path):
    value = controller(tmp_path, max_daily_cost_usd=0.000120)
    reservation = authorize(value)
    value.fail(reservation, reason="lost response")
    assert value.summary()["total_cost_usd"] is None
    assert value.summary()["reserved_cost_usd"] == pytest.approx(0.000116)
    with pytest.raises(CostLimitExceeded, match="daily model cost"):
        authorize(value)


def test_fake_backend_exception_cannot_leak_registered_secret_into_accounting(tmp_path):
    secret = "m35.fake.accounting.secret." + uuid.uuid4().hex
    register_sensitive_value(secret)
    value = controller(tmp_path)
    reservation = authorize(value)

    def backend():
        raise RuntimeError("fake backend failed: " + secret)

    try:
        backend()
    except RuntimeError as error:
        value.fail(reservation, reason=str(error), dispatched=True)
    assert secret not in str(value.summary())
    for path in tmp_path.glob("usage.sqlite3*"):
        assert secret.encode() not in path.read_bytes()


def test_known_secret_cannot_be_a_persisted_accounting_identifier(tmp_path):
    secret = "m35.fake.accounting.identifier." + uuid.uuid4().hex
    register_sensitive_value(secret)
    value = controller(tmp_path)
    with pytest.raises(CostLimitExceeded, match="sensitive material"):
        value.authorize(
            ModelRequest(task_id=secret), provider_id="provider", model_id="model"
        )
    assert secret.encode() not in value.database.read_bytes()


def test_successful_backend_metadata_is_redacted_before_return(tmp_path):
    secret = "m35.fake.accounting.metadata." + uuid.uuid4().hex
    register_sensitive_value(secret)
    value = controller(tmp_path)
    reservation = authorize(value)
    normalized, _ = value.commit(
        reservation,
        response(
            reservation,
            {"input_tokens": 3, "output_tokens": 2},
            metadata={"backend_diagnostic": secret},
        ),
    )
    assert secret not in str(normalized.metadata)


def test_old_database_migrates_without_inventing_measurement_provenance(tmp_path):
    database = tmp_path / "usage.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE usage_receipts (
                receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, day TEXT NOT NULL,
                request_id TEXT NOT NULL, task_id TEXT NOT NULL, provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL, credential_ref_hash TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL);
            INSERT INTO usage_receipts VALUES ('old', 'old', date('now'), 'original', 'task',
                'provider', 'model', 'credential-hash', 4, 2, 0, 6, 0, 1, 'completed');
        """)
    value = controller(tmp_path)
    summary = value.summary()
    assert summary["total_tokens"] is None and summary["total_cost_usd"] is None
    assert summary["receipts"][0]["cost_measurement"] == "legacy_unknown"
    assert summary["remaining"]["tokens"] == value.policy.max_daily_tokens - 6


def test_explicit_token_only_environment_preserves_inspection(monkeypatch):
    monkeypatch.setenv("APEIR_MAX_DAILY_COST_USD", "none")
    monkeypatch.setenv("APEIR_MAX_RETRY_COST_USD", "none")
    policy = CostPolicy.from_environment()
    assert policy.max_daily_cost_usd is None and policy.max_retry_cost_usd is None


@pytest.mark.parametrize(
    "field",
    ["messages", "tools", "response_schema", "response_format", "legacy_params"],
)
def test_caller_cannot_lower_actual_input_estimate(tmp_path, field):
    metadata = {"estimated_input_tokens": 1, "max_tokens": 8}
    messages = ({"role": "user", "content": "hello"},)
    if field == "messages":
        messages = ({"role": "user", "content": "x" * 1000},)
    else:
        metadata[field] = (
            [{"description": "x" * 1000}]
            if field == "tools"
            else {"description": "x" * 1000}
        )
    value = controller(tmp_path, max_input_tokens=80)
    with pytest.raises(CostLimitExceeded, match="input token"):
        value.authorize(
            ModelRequest(task_id="bounded-input", messages=messages, metadata=metadata),
            provider_id="provider",
            model_id="model",
        )
    assert value.summary()["reservations"] == []


@pytest.mark.parametrize("context,output,limit", [(107, 64, 7), (200, 6, 6)])
def test_model_windows_bound_all_forwarded_output_aliases(
    tmp_path, context, output, limit
):
    value = controller(tmp_path)
    request = ModelRequest(
        task_id="model-window",
        metadata={
            "estimated_input_tokens": 100,
            "max_tokens": 500,
            "max_output_tokens": 400,
            "max_completion_tokens": 600,
            "legacy_params": {"max_tokens": 900, "max_output_tokens": 900},
        },
    )
    reservation = value.authorize(
        request,
        provider_id="provider",
        model_id="model",
        context_window=context,
        output_window=output,
    )
    assert reservation.estimated_usage.output_tokens == limit
    assert {
        reservation.request.metadata[name]
        for name in ("max_tokens", "max_output_tokens", "max_completion_tokens")
    } == {limit}
    assert set(reservation.request.metadata["legacy_params"].values()) == {limit}
    assert request.metadata["max_tokens"] == 500


def test_no_output_space_in_model_context_rejects_before_reserving(tmp_path):
    value = controller(tmp_path)
    with pytest.raises(CostLimitExceeded, match="context window"):
        value.authorize(
            ModelRequest(
                task_id="full-context", metadata={"estimated_input_tokens": 100}
            ),
            provider_id="provider",
            model_id="model",
            context_window=100,
        )
    assert value.summary()["reservations"] == []


def test_an_invalid_output_alias_cannot_hide_behind_another_alias(tmp_path):
    value = controller(tmp_path)
    with pytest.raises(CostLimitExceeded, match="max_tokens"):
        authorize(value, max_tokens=True, max_output_tokens=8)
    assert value.summary()["reservations"] == []


def test_estimated_provider_counters_do_not_release_real_usage_budget(tmp_path):
    value = controller(tmp_path, max_daily_tokens=200)
    reservation = authorize(value)
    normalized, receipt = value.commit(
        reservation,
        response(
            reservation,
            {
                "input_tokens": 150,
                "output_tokens": 8,
                "counter_measurements": {
                    "input_tokens": "estimated",
                    "output_tokens": "estimated",
                },
            },
        ),
    )
    summary = value.summary()
    assert normalized.usage["counter_measurements"]["total_tokens"] == "estimated"
    assert receipt["status"] == "usage_unknown" and receipt["cost_usd"] is None
    assert (
        summary["total_tokens"] is None and summary["known_totals"]["total_tokens"] == 0
    )
    assert (
        summary["estimated_totals"]["total_tokens"] == summary["reserved_tokens"] == 158
    )
    assert summary["remaining"]["tokens"] == 42
    with pytest.raises(CostLimitExceeded, match="daily model token"):
        authorize(value)


def test_enabling_usd_policy_cannot_erase_prior_unpriced_uncertainty(tmp_path):
    unpriced = controller(
        tmp_path, price=False, max_daily_cost_usd=None, max_retry_cost_usd=None
    )
    reservation = authorize(unpriced)
    unpriced.fail(reservation, reason="lost unpriced response")
    priced = controller(tmp_path)
    with pytest.raises(CostLimitExceeded, match="previous model billing is unknown"):
        authorize(priced)
    assert priced.summary()["remaining"]["cost_usd"] is None
    assert priced.summary()["receipts"][0]["cost_usd"] is None


@pytest.mark.parametrize("mode", ["missing", "unpriced", "configured"])
def test_file_pricing_readiness_reports_actual_load_without_private_paths(
    tmp_path, monkeypatch, mode
):
    path = tmp_path / "PRIVATE-LOCAL-PRICING-PATH.json"
    if mode != "missing":
        path.write_text(
            json.dumps(
                {
                    "models": {
                        "provider/model": {
                            "input_per_million_usd": None if mode == "unpriced" else 1,
                            "output_per_million_usd": 2,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setenv("APEIR_MODEL_PRICING_FILE", str(path))
    value = CostController.from_environment()
    policy = value.summary()["policy"]
    assert policy["budget_mode"] == "usd"
    assert policy["pricing"]["configured"] is True
    assert policy["pricing"]["loaded"] is (mode != "missing")
    assert policy["pricing"]["status"] == mode
    assert policy["pricing"]["priced_models"] == int(mode == "configured")
    assert "PRIVATE-LOCAL-PRICING-PATH" not in str(policy)


def test_token_only_readiness_is_not_a_free_pricing_claim(tmp_path, monkeypatch):
    monkeypatch.delenv("APEIR_MODEL_PRICING_FILE", raising=False)
    monkeypatch.setenv("APEIR_MAX_DAILY_COST_USD", "none")
    monkeypatch.setenv("APEIR_MAX_RETRY_COST_USD", "none")
    policy = CostController.from_environment().summary()["policy"]
    assert policy["budget_mode"] == "token_only"
    assert policy["pricing"]["status"] == "unconfigured"
    assert (
        policy["pricing"]["configured"] is False
        and policy["pricing"]["loaded"] is False
    )
    assert policy["pricing"]["priced_models"] == 0


def kernel_request():
    return ModelRequest(
        task_id="original-kernel-task",
        messages=({"role": "user", "content": "PRIVATE-FAKE-KERNEL-INPUT"},),
        metadata={"estimated_input_tokens": 100, "max_tokens": 8},
    )


def kernel_arguments():
    return {
        "provider_id": "provider",
        "model_id": "model",
        "credential_ref": "env:APEIR_FAKE_API_KEY",
        "kernel_binding": {
            "kernel_endpoint": "tcp://fake-kernel:8771",
            "provider_endpoint": "https://fake.example/v1",
            "backend": "openai-compatible",
            "credential_env": "APEIR_FAKE_API_KEY",
        },
    }


@pytest.mark.parametrize(
    "field",
    [
        "messages",
        "tools",
        "max_tokens",
        "max_cost_usd",
        "provider_id",
        "model_id",
        "credential_ref",
        "provider_endpoint",
        "kernel_endpoint",
    ],
)
def test_original_kernel_bindings_cannot_change_after_restart(tmp_path, field):
    value = controller(tmp_path)
    request = kernel_request()
    arguments = kernel_arguments()
    reservation = value.authorize(request, **arguments)
    value.mark_dispatched(reservation)
    if field == "messages":
        request = replace(request, messages=({"role": "user", "content": "changed"},))
    elif field in {"tools", "max_tokens"}:
        request = replace(
            request,
            metadata={**request.metadata, field: [] if field == "tools" else 9},
        )
    elif field == "max_cost_usd":
        request = replace(request, max_cost_usd=1)
    elif field in arguments:
        arguments[field] = "changed-original-reference"
    else:
        arguments["kernel_binding"][field] = "changed-original-endpoint"
    reopened = controller(tmp_path)
    with pytest.raises(CostLimitExceeded, match="bindings cannot change"):
        reopened.authorize(request, **arguments)
    summary = reopened.summary()
    assert summary["reserved_tokens"] == 108 and summary["pending_requests"] == 1
    assert len(summary["reservations"]) == 1 and summary["receipts"] == []
    assert b"PRIVATE-FAKE-KERNEL-INPUT" not in value.database.read_bytes()


def test_crashed_kernel_dispatch_keeps_original_admission_and_charge(tmp_path):
    value = controller(tmp_path, max_daily_tokens=108)
    request = kernel_request()
    original = value.authorize(request, **kernel_arguments())
    value.mark_dispatched(original)
    reopened = controller(tmp_path, max_daily_tokens=108, max_output_tokens=4)
    retained = reopened.authorize(request, **kernel_arguments())
    assert retained.replayed and retained.reservation_id == original.reservation_id
    assert retained.estimated_usage.to_dict() == original.estimated_usage.to_dict()
    assert retained.estimated_cost_usd == original.estimated_cost_usd
    assert retained.request.metadata["max_tokens"] == 8
    with pytest.raises(CostLimitExceeded, match="new bound model attempt"):
        reopened.mark_dispatched(retained)
    reopened.fail(retained, reason="no read-only receipt proof", dispatched=False)
    assert reopened.summary()["reserved_tokens"] == 108
    reopened.commit(
        retained,
        response(
            retained,
            {"input_tokens": 100, "output_tokens": 2},
            cost_usd=0.000104,
            metadata={"cost_measurement": "reported"},
        ),
    )
    summary = reopened.summary()
    assert summary["requests"] == 1 and summary["reserved_tokens"] == 0
    assert summary["reported_cost_usd"] == pytest.approx(0.000104)


def test_atomic_kernel_replay_reserves_once_and_only_one_attempt_can_dispatch(tmp_path):
    values = [controller(tmp_path, max_daily_tokens=108) for _ in range(2)]
    request = kernel_request()
    ready = Barrier(2)

    def reserve(value):
        ready.wait(timeout=5)
        reservation = value.authorize(request, **kernel_arguments())
        try:
            value.mark_dispatched(reservation)
            return reservation.reservation_id, True
        except CostLimitExceeded:
            return reservation.reservation_id, False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, values))
    assert len({result[0] for result in results}) == 1
    assert sum(result[1] for result in results) == 1
    assert values[0].summary()["reserved_tokens"] == 108


def test_confirmed_kernel_predispatch_failure_allows_a_new_admitted_attempt(tmp_path):
    value = controller(tmp_path, max_daily_tokens=108)
    request = kernel_request()
    first = value.authorize(request, **kernel_arguments())
    value.fail(first, reason="connection setup failed", dispatched=False)
    second = value.authorize(request, attempt=2, **kernel_arguments())
    assert second.reservation_id != first.reservation_id and not second.replayed
    value.mark_dispatched(second)
    value.commit(
        second,
        response(
            second,
            {"input_tokens": 100, "output_tokens": 2},
            cost_usd=0.000104,
            metadata={"cost_measurement": "reported"},
        ),
    )
    summary = value.summary()
    assert summary["requests"] == 2 and summary["reserved_tokens"] == 0
    assert {receipt["status"] for receipt in summary["receipts"]} == {
        "not_dispatched",
        "completed",
    }
    assert summary["reported_cost_usd"] == pytest.approx(0.000104)


@pytest.mark.parametrize(
    "field", ["provider_id", "model_id", "attempt", "estimated_cost_usd"]
)
def test_original_kernel_reservation_cannot_be_rebound_during_commit(tmp_path, field):
    value = controller(tmp_path)
    original = value.authorize(kernel_request(), **kernel_arguments())
    value.mark_dispatched(original)
    changed = replace(
        original,
        **{
            field: 2
            if field == "attempt"
            else 0.0
            if field == "estimated_cost_usd"
            else "changed"
        },
    )
    with pytest.raises(CostLimitExceeded, match="reservation bindings cannot change"):
        value.commit(
            changed,
            response(
                changed,
                {"input_tokens": 100, "output_tokens": 2},
                cost_usd=0.000104,
                metadata={"cost_measurement": "reported"},
            ),
        )
    assert (
        value.summary()["reserved_tokens"] == 108 and value.summary()["receipts"] == []
    )


@pytest.mark.parametrize(
    "change",
    ["reported_counter", "derived_counter", "downgrade", "reported_cost"],
)
def test_partial_or_uncertain_receipt_cannot_rewrite_reported_evidence(
    tmp_path, change
):
    value = controller(
        tmp_path, price=False, max_daily_cost_usd=None, max_retry_cost_usd=None
    )
    original = authorize(value)
    initial = (
        response(original, cost_usd=0.25, metadata={"cost_measurement": "reported"})
        if change == "reported_cost"
        else response(original, {"input_tokens": 100, "output_tokens": 2})
    )
    value.commit(original, initial)
    value.fail(original, reason="late original acknowledgement", dispatched=True)
    prior = value.summary()["receipts"][0]
    usage = {"input_tokens": 100, "output_tokens": 2}
    if change == "reported_counter":
        usage["input_tokens"] = 1
    elif change == "derived_counter":
        usage["total_tokens"] = 103
    elif change == "downgrade":
        usage["counter_measurements"] = {"input_tokens": "estimated"}
    with pytest.raises(
        CostLimitExceeded, match="original (usage evidence|reported cost)"
    ):
        value.commit(
            original,
            response(
                original, usage, cost_usd=0, metadata={"cost_measurement": "reported"}
            ),
        )
    current = value.summary()["receipts"][0]
    assert current == prior
    assert value.summary()["requests"] == 1


def test_unknown_cost_and_counters_can_gain_original_reported_evidence(tmp_path):
    value = controller(
        tmp_path, price=False, max_daily_cost_usd=None, max_retry_cost_usd=None
    )
    original = authorize(value)
    _, first = value.commit(
        original, response(original, {"input_tokens": 100, "output_tokens": 2})
    )
    _, settled = value.commit(
        original,
        response(
            original,
            {
                "input_tokens": 100,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "reasoning_tokens": 0,
            },
            cost_usd=0,
            metadata={"cost_measurement": "reported"},
        ),
    )
    summary = value.summary()
    assert settled["receipt_id"] == first["receipt_id"]
    assert (
        settled["status"] == "completed" and settled["cost_measurement"] == "reported"
    )
    assert summary["requests"] == 1 and summary["total_tokens"] == 102
    assert summary["total_cost_usd"] == 0 and summary["reserved_tokens"] == 0


def test_reported_cost_is_preserved_when_original_unknown_usage_completes(tmp_path):
    value = controller(tmp_path)
    original = authorize(value)
    value.commit(
        original,
        response(original, cost_usd=0.25, metadata={"cost_measurement": "reported"}),
    )
    _, settled = value.commit(
        original,
        response(
            original,
            {"input_tokens": 100, "output_tokens": 2},
            cost_usd=0.25,
            metadata={"cost_measurement": "reported"},
        ),
    )
    assert settled["status"] == "completed" and settled["cost_usd"] == 0.25
    assert value.summary()["total_tokens"] == 102
    assert value.summary()["reserved_tokens"] == 0


def test_estimated_counters_require_stronger_original_evidence_to_release_budget(
    tmp_path,
):
    value = controller(tmp_path)
    original = authorize(value)
    estimated = {
        "input_tokens": 150,
        "output_tokens": 8,
        "counter_measurements": {
            "input_tokens": "estimated",
            "output_tokens": "estimated",
        },
    }
    value.commit(original, response(original, estimated))
    with pytest.raises(CostLimitExceeded, match="lose certainty"):
        value.commit(original, response(original, {**estimated, "input_tokens": 140}))
    assert value.summary()["reserved_tokens"] == 158
    value.commit(
        original, response(original, {"input_tokens": 100, "output_tokens": 2})
    )
    assert value.summary()["total_tokens"] == 102
    assert value.summary()["reserved_tokens"] == 0


@pytest.mark.parametrize(
    "counter", ["cached_input_tokens", "cache_creation_input_tokens"]
)
@pytest.mark.parametrize("cache_rate", [None, 0.0])
@pytest.mark.parametrize("tokens", [0, 100])
def test_observed_unpriced_cache_class_invalidates_only_nonzero_exposure(
    tmp_path, counter, cache_rate, tokens
):
    rate = Pricing(
        0,
        0,
        cache_rate if counter == "cached_input_tokens" else 0,
        cache_rate if counter == "cache_creation_input_tokens" else 0,
    )
    value = CostController(
        tmp_path / "usage.sqlite3", pricing=PricingCatalog({"provider/model": rate})
    )
    original = authorize(value)
    usage = {
        "input_tokens": 100,
        "output_tokens": 2,
        "cached_input_tokens": tokens if counter == "cached_input_tokens" else 0,
        "cache_creation_input_tokens": tokens
        if counter == "cache_creation_input_tokens"
        else 0,
    }
    _, receipt = value.commit(original, response(original, usage))
    reopened = CostController(
        value.database, pricing=PricingCatalog({"provider/model": rate})
    )
    summary = reopened.summary()
    unbounded = tokens > 0 and cache_rate is None
    assert summary["requests"] == 1 and summary["total_tokens"] == 102
    if unbounded:
        assert receipt["cost_usd"] is None and receipt["cost_measurement"] == "unknown"
        assert summary["reserved_cost_usd"] is None
        assert summary["remaining"]["cost_usd"] is None
        assert len(summary["reservations"]) == 1
        with pytest.raises(
            CostLimitExceeded, match="previous model billing is unknown"
        ):
            authorize(reopened)
    else:
        assert receipt["cost_usd"] == 0 and receipt["cost_measurement"] == "estimated"
        assert summary["reserved_cost_usd"] == 0
        assert summary["remaining"]["cost_usd"] == 5
        assert summary["reservations"] == []
        authorize(reopened)


def test_original_reported_cost_settles_unpriced_cache_class_after_restart(tmp_path):
    pricing = PricingCatalog({"provider/model": Pricing(0, 0, 0, None)})
    value = CostController(tmp_path / "usage.sqlite3", pricing=pricing)
    request = kernel_request()
    original = value.authorize(request, **kernel_arguments())
    value.mark_dispatched(original)
    usage = {
        "input_tokens": 100,
        "output_tokens": 2,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 100,
    }
    _, first = value.commit(original, response(original, usage))
    reopened = CostController(value.database, pricing=pricing)
    assert reopened.summary()["remaining"]["cost_usd"] is None
    retained = reopened.authorize(request, **kernel_arguments())
    assert retained.replayed and retained.reservation_id == original.reservation_id
    _, settled = reopened.commit(
        retained,
        response(
            retained, usage, cost_usd=0.25, metadata={"cost_measurement": "reported"}
        ),
    )
    summary = reopened.summary()
    assert settled["receipt_id"] == first["receipt_id"]
    assert summary["requests"] == 1 and summary["reserved_tokens"] == 0
    assert summary["reserved_cost_usd"] == 0 and summary["total_cost_usd"] == 0.25
    assert summary["remaining"]["cost_usd"] == 4.75
    authorize(reopened)


def test_reported_cost_restores_monetary_bound_while_original_tokens_remain_unknown(
    tmp_path,
):
    value = CostController(
        tmp_path / "usage.sqlite3",
        pricing=PricingCatalog({"provider/model": Pricing(0, 0, None, 0)}),
    )
    original = authorize(value)
    usage = {"cached_input_tokens": 100, "cache_creation_input_tokens": 0}
    value.commit(original, response(original, usage))
    assert value.summary()["reserved_cost_usd"] is None
    assert value.summary()["remaining"]["cost_usd"] is None
    value.commit(
        original,
        response(
            original, usage, cost_usd=0.25, metadata={"cost_measurement": "reported"}
        ),
    )
    summary = value.summary()
    assert summary["requests"] == 1 and summary["total_tokens"] is None
    assert summary["reserved_tokens"] == 108 and summary["reserved_cost_usd"] == 0
    assert (
        summary["total_cost_usd"] == 0.25 and summary["remaining"]["cost_usd"] == 4.75
    )
    authorize(value)
