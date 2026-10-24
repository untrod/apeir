from __future__ import annotations

from pathlib import Path

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


def _request(**metadata: object) -> ModelRequest:
    return ModelRequest(
        task_id="task-1",
        messages=({"role": "user", "content": "hello"},),
        metadata=metadata,
    )


def _controller(path: Path, **limits: object) -> CostController:
    policy = CostPolicy(**limits)
    pricing = PricingCatalog({"provider/model": Pricing(1.0, 2.0, 0.25)})
    return CostController(path / "usage.sqlite3", policy=policy, pricing=pricing)


def test_usage_normalizes_provider_field_names() -> None:
    usage = Usage.from_mapping(
        {
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 3},
        }
    )
    assert usage.to_dict() == {
        "input_tokens": 20,
        "output_tokens": 5,
        "cached_input_tokens": 4,
        "cache_miss_input_tokens": 16,
        "reasoning_tokens": 3,
        "total_tokens": 25,
        "cache_creation_input_tokens": None,
        "counter_measurements": {
            "input_tokens": "reported",
            "output_tokens": "reported",
            "cached_input_tokens": "reported",
            "cache_miss_input_tokens": "derived",
            "reasoning_tokens": "reported",
            "total_tokens": "derived",
            "cache_creation_input_tokens": "unknown",
        },
    }


def test_usage_normalizes_deepseek_and_anthropic_cache_fields() -> None:
    deepseek = Usage.from_mapping(
        {
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "prompt_cache_hit_tokens": 12,
            "prompt_cache_miss_tokens": 8,
        }
    )
    anthropic = Usage.from_mapping(
        {
            "input_tokens": 5,
            "output_tokens": 2,
            "cache_read_input_tokens": 7,
            "cache_creation_input_tokens": 3,
        }
    )

    assert deepseek.input_tokens == 20
    assert deepseek.cached_input_tokens == 12
    assert deepseek.cache_miss_input_tokens == 8
    assert anthropic.input_tokens == 15
    assert anthropic.cached_input_tokens == 7
    assert anthropic.cache_miss_input_tokens == 8


def test_request_is_capped_before_provider_execution(tmp_path: Path) -> None:
    controller = _controller(tmp_path, max_output_tokens=32)
    reservation = controller.authorize(
        _request(max_tokens=500), provider_id="provider", model_id="model"
    )
    assert reservation.request.metadata["max_tokens"] == 32
    assert reservation.estimated_usage.output_tokens == 32


def test_input_and_daily_limits_fail_closed(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        max_input_tokens=4,
        max_output_tokens=4,
        max_request_tokens=8,
        max_daily_tokens=8,
    )
    with pytest.raises(CostLimitExceeded, match="input token"):
        controller.authorize(
            _request(estimated_input_tokens=5),
            provider_id="provider",
            model_id="model",
        )


def test_receipt_is_durable_and_grouped_without_api_key_value(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    reservation = controller.authorize(
        _request(max_tokens=10),
        provider_id="provider",
        model_id="model",
        credential_ref="env:API_KEY_ONE",
    )
    response, receipt = controller.commit(
        reservation,
        ModelResponse(
            request_id=reservation.request.request_id,
            model_id="model",
            instance_id="instance",
            usage={"input_tokens": 10, "output_tokens": 5},
        ),
    )
    assert response.usage["total_tokens"] == 15
    assert response.cost_usd == pytest.approx(0.00002)
    assert "API_KEY_ONE" not in str(receipt)
    reopened = _controller(tmp_path)
    summary = reopened.summary()
    assert summary["total_tokens"] == 15
    assert summary["items"][0]["task_id"] == "task-1"


def test_balance_exhaustion_blocks_later_requests_for_same_reference(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    reservation = controller.authorize(
        _request(),
        provider_id="provider",
        model_id="model",
        credential_ref="env:API_KEY_ONE",
    )
    controller.fail(
        reservation,
        reason="insufficient balance",
        balance_exhausted=True,
    )
    with pytest.raises(CostLimitExceeded, match="spending is blocked"):
        controller.authorize(
            _request(),
            provider_id="provider",
            model_id="model",
            credential_ref="env:API_KEY_ONE",
        )


def test_retry_attempt_and_retry_token_budgets_are_enforced(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        max_attempts=2,
        max_retry_tokens=10,
        max_output_tokens=8,
        max_request_tokens=100,
    )
    with pytest.raises(CostLimitExceeded, match="retry token"):
        controller.authorize(
            _request(estimated_input_tokens=4, max_tokens=8),
            provider_id="provider",
            model_id="model",
            attempt=2,
        )
    with pytest.raises(CostLimitExceeded, match="attempt"):
        controller.authorize(
            _request(),
            provider_id="provider",
            model_id="model",
            attempt=3,
        )


def test_provider_output_overrun_is_recorded_and_blocks_followup(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, max_output_tokens=8)
    reservation = controller.authorize(
        _request(max_tokens=8),
        provider_id="provider",
        model_id="model",
        credential_ref="env:RUNAWAY_KEY",
    )
    with pytest.raises(CostLimitExceeded, match="provider response"):
        controller.commit(
            reservation,
            ModelResponse(
                request_id=reservation.request.request_id,
                model_id="model",
                instance_id="instance",
                usage={"input_tokens": 2, "output_tokens": 9},
            ),
        )
    summary = controller.summary()
    assert summary["total_tokens"] == 11
    with pytest.raises(CostLimitExceeded, match="spending is blocked"):
        controller.authorize(
            _request(),
            provider_id="provider",
            model_id="model",
            credential_ref="env:RUNAWAY_KEY",
        )


def test_summary_reports_cache_and_remaining_budget(tmp_path: Path) -> None:
    controller = _controller(tmp_path, max_daily_tokens=100)
    reservation = controller.authorize(
        _request(max_tokens=10), provider_id="provider", model_id="model"
    )
    controller.commit(
        reservation,
        ModelResponse(
            request_id=reservation.request.request_id,
            model_id="model",
            instance_id="instance",
            usage={
                "input_tokens": 10,
                "cached_input_tokens": 6,
                "output_tokens": 5,
            },
        ),
    )
    summary = controller.summary()
    assert summary["cached_input_tokens"] == 6
    assert summary["remaining"]["tokens"] == 85
    assert summary["policy"]["max_daily_tokens"] == 100


def test_request_usage_preserves_all_attempts_and_open_reservations(tmp_path):
    controller = _controller(tmp_path)
    original = _request(estimated_input_tokens=10, max_tokens=8)
    first = controller.authorize(original, provider_id="provider", model_id="model")
    controller.fail(first, reason="not dispatched", dispatched=False)
    assert controller.request_usage(original.request_id) == (0.0, 0)
    assert controller.request_usage("unknown-request") == (None, None)
    second = controller.authorize(
        original, provider_id="provider", model_id="model", attempt=2
    )
    # The first derived-zero receipt cannot hide an open second attempt.
    assert controller.request_usage(original.request_id) == (None, None)
    controller.mark_dispatched(second)
    controller.fail(second, reason="response lost", dispatched=True)
    assert controller.request_usage(original.request_id) == (None, None)
    assert controller.summary()["uncertain_calls"] == 1
    with controller._session() as connection:
        for table in ("usage_receipts", "usage_reservations"):
            plans = connection.execute(
                f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE request_id=?",
                (original.request_id,),
            ).fetchall()
            assert any(f"{table}_request_idx" in row[3] for row in plans)


@pytest.mark.parametrize("corruption", ["json", "binding", "negative_cost", "usage"])
def test_request_usage_rejects_corrupt_zero_effect_evidence(tmp_path, corruption):
    import json

    controller = _controller(tmp_path)
    original = _request(estimated_input_tokens=10, max_tokens=8)
    reservation = controller.authorize(
        original, provider_id="provider", model_id="model"
    )
    controller.fail(reservation, reason="not dispatched", dispatched=False)
    with controller._session(immediate=True) as connection:
        raw = connection.execute(
            "SELECT receipt_json FROM usage_receipts WHERE request_id=?",
            (original.request_id,),
        ).fetchone()[0]
        value = json.loads(raw)
        if corruption == "json":
            damaged = "{"
        else:
            if corruption == "binding":
                value["request_id"] = "different-original-request"
            elif corruption == "negative_cost":
                value["cost_usd"] = -1
            else:
                value["usage"]["total_tokens"] = -1
            damaged = json.dumps(value)
        connection.execute(
            "UPDATE usage_receipts SET receipt_json=? WHERE request_id=?",
            (damaged, original.request_id),
        )
    with pytest.raises(
        CostLimitExceeded, match="original request usage evidence is invalid"
    ):
        controller.request_usage(original.request_id)
