"""Inspector snapshot for the unified model runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nous_runtime.model_runtime.gateway import ModelGateway
from nous_runtime.model_runtime.models import ModelLifecycleState, utc_now


@dataclass(frozen=True)
class ModelRuntimeSnapshot:
    captured_at: str
    model_states: Mapping[str, int]
    instance_states: Mapping[str, int]
    resource_usage: Mapping[str, int]
    metrics: Mapping[str, float | int]
    active_request_ids: tuple[str, ...]
    recent_events: tuple[Mapping[str, Any], ...]

    @property
    def healthy(self) -> bool:
        return (
            self.model_states.get(ModelLifecycleState.BROKEN.value, 0)
            == 0
            and self.instance_states.get("failed", 0) == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "healthy": self.healthy,
            "model_states": dict(self.model_states),
            "instance_states": dict(self.instance_states),
            "resource_usage": dict(self.resource_usage),
            "metrics": dict(self.metrics),
            "active_request_ids": list(self.active_request_ids),
            "recent_events": [
                dict(item) for item in self.recent_events
            ],
        }


def capture_model_runtime(
    gateway: ModelGateway,
    *,
    event_limit: int = 20,
) -> ModelRuntimeSnapshot:
    model_states = {item.value: 0 for item in ModelLifecycleState}
    for record in gateway.registry.list(include_removed=True):
        model_states[record.state.value] += 1
    instance_states: dict[str, int] = {}
    for instance in gateway.registry.list_instances():
        instance_states[instance.state.value] = (
            instance_states.get(instance.state.value, 0) + 1
        )
    normalized_limit = max(0, event_limit)
    events = (
        tuple(gateway.events)[-normalized_limit:]
        if normalized_limit
        else ()
    )
    return ModelRuntimeSnapshot(
        captured_at=utc_now(),
        model_states=model_states,
        instance_states=instance_states,
        resource_usage=gateway.scheduler.resource_usage(),
        metrics=gateway.metrics_snapshot(),
        active_request_ids=gateway.active_request_ids(),
        recent_events=tuple(event.to_dict() for event in events),
    )


__all__ = ["ModelRuntimeSnapshot", "capture_model_runtime"]
