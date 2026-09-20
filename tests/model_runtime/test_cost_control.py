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
    pricing = PricingCatalog(
        {"provider/model": Pricing(1.0, 2.0, 0.25)}
    )
    return CostController(path / "usage.sqlite3", policy=policy, pricing=pricing)


def test_usage_normalizes_provider_field_names() -> None:
    usage = Usage.from_mapping(
        {
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 4},
        }
    )
    assert usage.to_dict() == {
        "input_tokens": 20,
        "output_tokens": 5,
        "cached_input_tokens": 4,
        "total_tokens": 25,
    }


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


def test_balance_exhaustion_blocks_later_requests_for_same_reference(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    reservation = controller.authorize(
        _request(), provider_id="provider", model_id="model",
        credential_ref="env:API_KEY_ONE",
    )
    controller.fail(
        reservation,
        reason="insufficient balance",
        balance_exhausted=True,
    )
    with pytest.raises(CostLimitExceeded, match="spending is blocked"):
        controller.authorize(
            _request(), provider_id="provider", model_id="model",
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
            provider_id="provider", model_id="model", attempt=2,
        )
    with pytest.raises(CostLimitExceeded, match="attempt"):
        controller.authorize(
            _request(), provider_id="provider", model_id="model", attempt=3,
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
