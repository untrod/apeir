from __future__ import annotations

from nous_runtime.intelligence.reliability.executor import _invoke_provider
from nous_runtime.model_runtime.compatibility import (
    compatibility_events,
    compatibility_metrics,
    reset_compatibility_observability,
    try_invoke_legacy_provider,
)
from nous_runtime.model_runtime.factory import (
    build_gateway_from_providers,
    gateway_service,
)


class LegacyReasonProvider:
    provider_id = "legacy-reason"
    provider_name = "Legacy Reason"
    model = "reason-model"
    max_concurrency = 1

    def __init__(self) -> None:
        self.invocations = 0

    def list_capabilities(self):
        return ["model.reason"]

    def health(self):
        return {"status": "ok"}

    def invoke(self, capability_id, **payload):
        self.invocations += 1
        return {
            "ok": True,
            "result": {
                "capability": capability_id,
                "messages": payload.get("messages"),
            },
            "usage": {"total_tokens": 7},
            "model": self.model,
        }


def test_reliability_executor_prefers_gateway_for_legacy_provider() -> None:
    reset_compatibility_observability()
    provider = LegacyReasonProvider()
    gateway = gateway_service.configure(
        build_gateway_from_providers([provider], allow_direct=True)
    )
    try:
        result = _invoke_provider(
            provider.provider_id,
            "model.reason",
            {
                "messages": [{"role": "user", "content": "reason"}],
            },
            execution_id="execution",
        )
    finally:
        gateway_service.clear()
        gateway.close_sync_bridge()

    assert result.success is True
    assert result.retry_metadata["gateway_routed"] is True
    assert result.token_usage["total_tokens"] == 7
    assert provider.invocations == 1
    assert compatibility_metrics()["gateway_invocations"] == 1
    assert compatibility_metrics()["direct_fallbacks"] == 0


def test_unconfigured_gateway_records_deprecated_fallback_event() -> None:
    gateway_service.clear()
    reset_compatibility_observability()

    result = try_invoke_legacy_provider(
        "legacy",
        "model.reason",
        {},
        execution_id="execution",
    )

    assert result is None
    assert compatibility_metrics()["direct_fallbacks"] == 1
    event = compatibility_events()[0]
    assert event.event_type == "model.compatibility.deprecated"
    assert event.payload["replacement"] == "ModelGatewayFacade"
    assert "secret" not in str(event.to_dict()).casefold()
