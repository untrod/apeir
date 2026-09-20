from __future__ import annotations

from nous_runtime.model_runtime import (
    HardwareBudget,
    ModelCapabilityResolver,
    ModelModality,
    ModelPackage,
    ModelRole,
    ModelRoleBinding,
    ModelRoleBindings,
    ModelRequest,
    RoutingMode,
    detect_hardware_budget,
)
from nous_runtime.model_runtime.integration import model_request_from_task
from nous_runtime.task import Task


def package(
    package_id: str,
    capabilities: set[str],
    modalities: set[ModelModality],
    disk_mb: int,
    *,
    approved: bool = True,
) -> ModelPackage:
    return ModelPackage(
        package_id=package_id,
        model_id=package_id,
        capabilities=frozenset(capabilities),
        modalities=frozenset(modalities),
        disk_mb=disk_mb,
        license_approved=approved,
    )


def test_capability_resolver_prefers_installed_minimal_set() -> None:
    resolver = ModelCapabilityResolver(
        [
            package(
                "installed-text",
                {"reasoning"},
                {ModelModality.TEXT},
                4000,
            ),
            package(
                "vision",
                {"vision"},
                {ModelModality.IMAGE},
                2000,
            ),
            package(
                "all-large",
                {"reasoning", "vision"},
                {ModelModality.TEXT, ModelModality.IMAGE},
                9000,
            ),
            package(
                "unapproved",
                {"reasoning", "vision"},
                {ModelModality.TEXT, ModelModality.IMAGE},
                1,
                approved=False,
            ),
        ]
    )
    result = resolver.resolve(
        capabilities={"reasoning", "vision"},
        modalities={ModelModality.TEXT, ModelModality.IMAGE},
        installed_packages={"installed-text"},
        hardware=HardwareBudget(disk_mb=3000),
    )
    assert result.complete
    assert [
        item.package_id for item in result.selected_packages
    ] == ["installed-text", "vision"]
    assert result.estimated_disk_mb == 2000
    assert "unapproved packages excluded" in result.warnings[0]


def test_task_and_role_requirements_merge_without_bypassing_gateway() -> None:
    task = Task(
        name="review",
        metadata={
            "required_capabilities": ["reasoning"],
            "privacy_policy": "private",
            "preferred_models": ["local"],
        },
    )
    request = model_request_from_task(
        task,
        messages=({"role": "user", "content": "review"},),
        role=ModelRole.REVIEWER,
    )
    bindings = ModelRoleBindings()
    bindings.bind(
        ModelRoleBinding(
            role=ModelRole.REVIEWER,
            preferred_models=("reviewer",),
            required_capabilities=frozenset({"verification"}),
        )
    )
    merged = bindings.apply(request)
    assert merged.required_capabilities == {
        "reasoning",
        "verification",
    }
    assert merged.preferred_models == ("local", "reviewer")
    assert merged.routing_mode is RoutingMode.PREFERRED


def test_model_request_rejects_invalid_timeout() -> None:
    try:
        ModelRequest(task_id="task", timeout_s=0)
    except Exception as exc:
        assert "timeout_s" in str(exc)
    else:
        raise AssertionError("invalid timeout was accepted")


def test_hardware_detection_and_memory_filter(tmp_path) -> None:
    detected = detect_hardware_budget(tmp_path)
    assert detected.disk_mb > 0
    resolver = ModelCapabilityResolver(
        [
            ModelPackage(
                package_id="large",
                model_id="large",
                capabilities=frozenset({"reasoning"}),
                modalities=frozenset({ModelModality.TEXT}),
                disk_mb=1,
                metadata={"memory_mb": 4096},
            )
        ]
    )
    resolution = resolver.resolve(
        capabilities={"reasoning"},
        hardware=HardwareBudget(
            disk_mb=10,
            memory_mb=1024,
            allow_gpu_packages=False,
        ),
    )
    assert resolution.complete is False
