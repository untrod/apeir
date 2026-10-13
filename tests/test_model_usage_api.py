from __future__ import annotations

import json

import pytest

from nous_runtime.api.developer_routes import handle_developer_model_lab
from nous_runtime.api.routes import handle_usage_summary
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.model_runtime.cost_control import CostController
from nous_runtime.model_runtime.models import ModelRequest, ModelResponse


@pytest.fixture
def accounting_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("APEIR_STATE_DIR", str(tmp_path / "private-state"))
    pricing = tmp_path / "fake-pricing.json"
    pricing.write_text(
        json.dumps(
            {
                "models": {
                    "fixture/model": {
                        "input_per_million_usd": 1,
                        "output_per_million_usd": 2,
                        "cached_input_per_million_usd": 0.25,
                        "cache_creation_input_per_million_usd": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APEIR_MODEL_PRICING_FILE", str(pricing))
    return CostController.from_environment()


def _record(controller, *, usage=None, cost=0.25, measurement="reported"):
    request = ModelRequest(
        request_id="request-fixture",
        task_id="task-fixture",
        messages=({"role": "user", "content": "PRIVATE-PROMPT-FIXTURE"},),
        metadata={"max_tokens": 16},
    )
    reservation = controller.authorize(
        request, provider_id="fixture", model_id="model", attempt=1
    )
    response = ModelResponse(
        request_id=request.request_id,
        model_id="model",
        instance_id="instance-fixture",
        usage=usage or {},
        cost_usd=cost,
        metadata={"cost_measurement": measurement},
    )
    return controller.commit(reservation, response)[1]


def test_model_lab_and_usage_project_the_same_durable_receipt(accounting_environment):
    receipt = _record(
        accounting_environment,
        usage={
            "input_tokens": 12,
            "output_tokens": 4,
            "cached_input_tokens": 2,
            "cache_creation_input_tokens": 0,
            "reasoning_tokens": 1,
        },
    )
    usage = handle_usage_summary()
    model_lab = handle_developer_model_lab()

    assert usage["ok"] is True
    assert model_lab["data"]["usage_accounting_status"] == "available"
    assert model_lab["data"]["usage_accounting"] == usage["data"]
    assert usage["data"]["receipts"][0]["receipt_id"] == receipt["receipt_id"]
    assert usage["data"]["receipts"][0]["request_id"] == "request-fixture"
    assert usage["data"]["receipts"][0]["attempt"] == 1
    assert usage["data"]["total_cost_usd"] == pytest.approx(0.25)
    assert usage["data"]["cost_measurement"] == "reported"
    assert (
        usage["data"]["receipts"][0]["usage"]["counter_measurements"]["total_tokens"]
        == "derived"
    )
    assert "PRIVATE-PROMPT-FIXTURE" not in json.dumps(model_lab)


def test_empty_journal_is_not_a_reported_zero_cost(accounting_environment):
    response = handle_usage_summary()

    assert response["ok"] is True
    assert response["data"]["requests"] == 0
    assert response["data"]["receipts"] == []
    assert response["data"]["cost_measurement"] == "no_receipts"
    assert response["data"]["reported_cost_requests"] == 0


def test_reported_zero_retains_its_measurement_and_cache_counters(
    accounting_environment,
):
    receipt = _record(
        accounting_environment,
        usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cache_miss_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        },
        cost=0,
    )
    response = handle_usage_summary()["data"]

    assert response["requests"] == 1
    assert response["total_cost_usd"] == 0
    assert response["cost_measurement"] == "reported"
    assert response["reported_cost_requests"] == 1
    assert response["unknown_cost_requests"] == 0
    assert response["receipts"][0] == redact_sensitive_data(receipt)
    assert receipt["usage"]["cache_creation_input_tokens"] == 0
    assert receipt["usage"]["counter_measurements"]["cached_input_tokens"] == "reported"
    assert response["pending_requests"] == 0


def test_pending_request_retains_unknown_spend_and_bound_reservation(
    accounting_environment,
):
    request = ModelRequest(
        request_id="pending-request",
        task_id="pending-task",
        messages=({"role": "user", "content": "PRIVATE-PENDING-PROMPT"},),
        metadata={"max_tokens": 16},
    )
    reservation = accounting_environment.authorize(
        request, provider_id="fixture", model_id="model", attempt=2
    )
    response = handle_developer_model_lab()["data"]["usage_accounting"]

    assert response["requests"] == 0
    assert response["receipts"] == []
    assert response["pending_requests"] == 1
    assert response["total_cost_usd"] is None
    assert response["cost_measurement"] == "unknown"
    assert response["total_tokens"] is None
    assert response["reserved_tokens"] == reservation.estimated_usage.total_tokens
    assert response["reserved_cost_usd"] == reservation.estimated_cost_usd
    assert response["reservations"][0]["reservation_id"] == reservation.reservation_id
    assert response["reservations"][0]["request_id"] == request.request_id
    assert response["reservations"][0]["attempt"] == 2
    assert response["reservations"][0]["receipt_recorded"] is False
    assert "PRIVATE-PENDING-PROMPT" not in json.dumps(response)


def test_unknown_usage_and_cost_survive_api_redaction(accounting_environment):
    _record(accounting_environment, cost=0, measurement="unknown")
    response = handle_usage_summary()

    assert response["ok"] is True
    assert response["data"]["input_tokens"] is None
    assert response["data"]["total_cost_usd"] is None
    assert response["data"]["unknown_cost_requests"] == 1
    receipt = response["data"]["receipts"][0]
    assert receipt["cost_usd"] is None
    assert receipt["cost_measurement"] == "unknown"
    assert receipt["usage"]["cached_input_tokens"] is None
    assert receipt["usage"]["counter_measurements"]["cached_input_tokens"] == "unknown"


def test_api_reads_current_pricing_and_token_only_policy(
    accounting_environment, tmp_path, monkeypatch
):
    configured = handle_usage_summary()["data"]["policy"]
    assert configured["pricing"]["status"] == "configured"
    assert configured["pricing"]["priced_models"] == 1
    assert configured["budget_mode"] == "usd"

    monkeypatch.setenv(
        "APEIR_MODEL_PRICING_FILE", str(tmp_path / "absent-pricing.json")
    )
    monkeypatch.setenv("APEIR_MAX_DAILY_COST_USD", "none")
    monkeypatch.setenv("APEIR_MAX_RETRY_COST_USD", "none")
    current = handle_developer_model_lab()["data"]["usage_accounting"]

    assert current["policy"]["pricing"]["status"] == "missing"
    assert current["policy"]["pricing"]["loaded"] is False
    assert current["policy"]["budget_mode"] == "token_only"
    assert current["policy"]["max_daily_cost_usd"] is None
    assert current["policy"]["max_retry_cost_usd"] is None
    assert current["remaining"]["cost_usd"] is None
    assert "absent-pricing.json" not in json.dumps(current)


def test_usage_read_failure_is_unavailable_without_echoing_private_exception(
    accounting_environment, monkeypatch
):
    def unavailable(cls):
        raise RuntimeError("PRIVATE_ACCOUNTING_PATH_AND_PROVIDER_FAILURE")

    monkeypatch.setattr(CostController, "from_environment", classmethod(unavailable))

    response = handle_usage_summary()
    model_lab = handle_developer_model_lab()

    assert response["ok"] is False
    assert response["error"]["message"] == "Model usage accounting is unavailable."
    assert "PRIVATE_ACCOUNTING" not in json.dumps(response)
    assert model_lab["ok"] is True
    assert model_lab["data"]["usage_accounting"] is None
    assert model_lab["data"]["usage_accounting_status"] == "unavailable"
    assert "PRIVATE_ACCOUNTING" not in json.dumps(model_lab)


def test_model_lab_preserves_selected_usage_day(accounting_environment):
    day = "2000-01-01"
    response = handle_developer_model_lab({"day": day})

    assert response["data"]["usage_accounting"]["day"] == day
    assert (
        response["data"]["usage_accounting"]
        == handle_usage_summary({"day": day})["data"]
    )
