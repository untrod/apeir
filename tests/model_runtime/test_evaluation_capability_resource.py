from __future__ import annotations

from nous_runtime.model_runtime import (
    CapabilityLevel,
    CostScheduler,
    HardwareScheduler,
    HardwareSnapshot,
    ModelCapabilityGraph,
    ModelDescriptor,
    ModelEndpointType,
    ModelEvaluation,
    ModelEvaluationStore,
    ModelInstance,
    ModelInstanceState,
    ModelRequest,
    ModelRuntimeRegistry,
)


def add_model(
    registry: ModelRuntimeRegistry,
    model_id: str,
    *,
    local: bool,
    coding: CapabilityLevel,
) -> None:
    registry.register(
        ModelDescriptor(
            model_id=model_id,
            display_name=model_id,
            provider_id="mock",
            endpoint_type=(
                ModelEndpointType.LOCAL_SERVICE
                if local
                else ModelEndpointType.CLOUD_API
            ),
            capabilities=frozenset({"reasoning", "coding"}),
            coding_level=coding,
            reasoning_level=coding,
        )
    )
    registry.enable(model_id)
    registry.register_instance(
        ModelInstance(
            instance_id=f"{model_id}-0",
            model_id=model_id,
            node_id="node",
            backend="mock",
            state=ModelInstanceState.READY,
        )
    )


def test_evaluation_store_persists_and_ranks(tmp_path) -> None:
    path = tmp_path / "evaluations.json"
    store = ModelEvaluationStore(path)
    store.record(ModelEvaluation("fast", "coding", 0.8, 100, 0.1))
    store.record(ModelEvaluation("slow", "coding", 0.9, 9000, 0.9))
    assert store.leaderboard(task_type="coding")[0].model_id == "fast"
    assert ModelEvaluationStore(path).summary("fast").sample_count == 1


def test_capability_graph_composes_model_roles() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "strong", local=False, coding=CapabilityLevel.HIGH)
    graph = ModelCapabilityGraph(registry)
    plan = graph.software_delivery_plan("task")
    assert [item.role.value for item in plan.assignments] == [
        "planner",
        "code_worker",
        "reviewer",
    ]
    assert plan.model_ids == ("strong", "strong", "strong")


def test_hardware_scheduler_prefers_local_accelerated_models() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "local", local=True, coding=CapabilityLevel.MEDIUM)
    add_model(registry, "cloud", local=False, coding=CapabilityLevel.HIGH)
    scheduler = HardwareScheduler(
        registry,
        HardwareSnapshot(
            cpu_count=16,
            ram_available_mb=32_000,
            disk_available_mb=100_000,
            gpu_available=True,
            vram_available_mb=16_000,
        ),
    )
    prepared = scheduler.prepare(
        ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"coding"}),
        )
    )
    assert prepared.locality_preference == "local"
    assert prepared.preferred_models == ("local",)
    assert scheduler.route(prepared.request).selected_model_id == "local"


def test_cost_scheduler_uses_canonical_router() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "model", local=False, coding=CapabilityLevel.HIGH)
    decision = CostScheduler(registry).route(
        ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"coding"}),
        )
    )
    assert decision.selected_model_id == "model"
