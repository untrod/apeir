from nous_runtime.intelligence.routing import CapabilityRouter, route_capabilities
from nous_runtime.intelligence.task import analyze_task
from nous_runtime.model import ModelProfile, ModelRegistry


def test_coding_route_uses_weighted_scores() -> None:
    registry = ModelRegistry([
        ModelProfile("fast", "test", ("coding", "reasoning"), coding_score=0.5, reasoning_score=0.5, speed_score=1.0, cost_score=1.0),
        ModelProfile("expert", "test", ("coding", "reasoning"), coding_score=1.0, reasoning_score=1.0, speed_score=0.4, cost_score=0.3),
    ])

    decision = CapabilityRouter(registry).route(analyze_task("Write Python code", task_id="t1"))

    assert decision.selected_model == "expert"
    assert decision.candidate_models == ("expert", "fast")
    assert "weighted capability match" in decision.reason


def test_private_route_selects_local_model() -> None:
    registry = ModelRegistry([
        ModelProfile("cloud", "test", ("reasoning", "local_execution"), reasoning_score=1.0),
        ModelProfile("local", "test", ("reasoning", "local_execution"), reasoning_score=0.6, privacy_level="local"),
    ])

    decision = route_capabilities(analyze_task("Use a private local model"), registry=registry)

    assert decision.selected_model == "local"


def test_routing_decision_serializes() -> None:
    payload = route_capabilities(analyze_task("calculate math", task_id="math")).to_dict()

    assert payload["task_id"] == "math"
    assert payload["selected_model"]
    assert isinstance(payload["candidate_models"], list)
