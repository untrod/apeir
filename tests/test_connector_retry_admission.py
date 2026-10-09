"""Declared retry budgets cannot authorize another non-idempotent effect."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.connectors.base import ConnectorTemporaryError
from nous_runtime.connectors.models import ConnectorRequest
from tests.test_connector_runtime import FakeGate, context, manifest, runtime


class EffectThenResponseLost:
    def __init__(self):
        self.effects = 0

    def execute(self, request, credential):
        self.effects += 1
        raise ConnectorTemporaryError("fake response lost after effect")

    def health(self):
        return {"status": "degraded"}


def test_non_idempotent_effect_response_loss_is_not_retried(tmp_path):
    item = manifest(scopes=("records.read", "records.write"))
    item = replace(
        item,
        actions=tuple(replace(action, idempotent=False) for action in item.actions),
    )
    gate = FakeGate()
    service, _, _ = runtime(tmp_path, item, gate=gate)
    adapter = EffectThenResponseLost()
    service.bind(item.connector_id, adapter)
    result = service.execute(
        ConnectorRequest(item.connector_id, "create", "workspace"), context=context()
    )
    assert not result.ok and result.error_code == "CONNECTOR_ERROR"
    assert result.attempts == adapter.effects == 1
    assert len(gate.proposals) == 1
    assert gate.proposals[0][0].retry_behavior == "non_idempotent"


@pytest.mark.parametrize("budget", [0, 1, 2, 3])
def test_idempotent_temporary_failures_stop_at_declared_retry_budget(tmp_path, budget):
    item = replace(manifest(), max_retries=budget)
    service, _, _ = runtime(tmp_path, item)
    adapter = EffectThenResponseLost()
    service.bind(item.connector_id, adapter)
    result = service.execute(
        ConnectorRequest(item.connector_id, "list", "workspace"), context=context()
    )
    assert not result.ok and result.error_code == "CONNECTOR_ERROR"
    assert result.attempts == adapter.effects == budget + 1


def test_idempotent_success_within_retry_budget_is_preserved(tmp_path):
    item = replace(manifest(), max_retries=2)
    service, _, _ = runtime(tmp_path, item)

    class EventuallySuccessful(EffectThenResponseLost):
        def execute(self, request, credential):
            if self.effects < 2:
                return super().execute(request, credential)
            self.effects += 1
            return SimpleNamespace(
                ok=True, items=(), next_cursor="", error_code="", message=""
            )

    adapter = EventuallySuccessful()
    service.bind(item.connector_id, adapter)
    result = service.execute(
        ConnectorRequest(item.connector_id, "list", "workspace"), context=context()
    )
    assert result.ok and result.attempts == adapter.effects == 3


@pytest.mark.parametrize("value, expected", [(0, 0), (None, 2), ("omitted", 2)])
def test_manifest_retry_budget_round_trip_preserves_zero_and_defaults(value, expected):
    from nous_runtime.connectors.models import ConnectorManifest

    data = manifest().to_dict()
    if value == "omitted":
        data.pop("max_retries")
    else:
        data["max_retries"] = value
    restored = ConnectorManifest.from_dict(data)
    assert restored.max_retries == expected
    assert ConnectorManifest.from_dict(restored.to_dict()).max_retries == expected
