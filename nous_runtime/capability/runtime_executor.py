"""Canonical dispatcher for built-in Runtime service capabilities.

Model inference is submitted through NKI. These bounded local services execute
in the Python Runtime after authorization and never claim Rust Kernel effects.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Callable, Mapping


class RuntimeCapabilityError(ValueError):
    """A Runtime capability cannot be dispatched with the supplied request."""


def _workspace_root(value: str | Path | None = None) -> Path:
    root = (
        Path(value or os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd())
        .expanduser()
        .resolve()
    )
    if not root.is_dir():
        raise RuntimeCapabilityError("the active workspace does not exist")
    return root


def _required_text(params: Mapping[str, Any], name: str) -> str:
    value = str(params.get(name) or "").strip()
    if not value:
        raise RuntimeCapabilityError(f"{name} is required")
    return value


def _document_create(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.documents import DocumentRuntime

    return DocumentRuntime(root).create(params)


def _document_render(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.documents import DocumentRuntime

    formats = params.get("formats") or ["docx", "pdf"]
    if not isinstance(formats, (list, tuple)):
        raise RuntimeCapabilityError("formats must be an array")
    return DocumentRuntime(root).render(
        _required_text(params, "document_id"), list(formats)
    )


def _environment_create(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.environments import EnvironmentRuntime

    return EnvironmentRuntime(root).create(params)


def _environment_lifecycle(
    operation: str,
) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    def execute(root: Path, params: dict[str, Any]) -> dict[str, Any]:
        from nous_runtime.environments import EnvironmentRuntime

        runtime = EnvironmentRuntime(root)
        environment_id = _required_text(params, "environment_id")
        if operation == "run":
            request = dict(params)
            request.pop("environment_id", None)
            return runtime.run(environment_id, request)
        return getattr(runtime, operation)(environment_id)

    return execute


def _simulation_create(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.simulations import SimulationRuntime

    return SimulationRuntime(root).create(params)


def _simulation_run(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.simulations import SimulationRuntime

    return SimulationRuntime(root).run(
        _required_text(params, "simulation_id"),
        replay_of=str(params.get("replay_of") or ""),
    )


def _simulation_replay(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.simulations import SimulationRuntime

    return SimulationRuntime(root).replay(_required_text(params, "run_id"))


def _simulation_cancel(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.simulations import SimulationRuntime

    return SimulationRuntime(root).cancel(_required_text(params, "simulation_id"))


def _scientific_analyze(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.scientific import ScientificRuntime

    return ScientificRuntime(root).analyze(params)


def _network_fetch(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.evidence.service import ResearchEvidenceService

    service = ResearchEvidenceService(root)
    result = (
        service.search(params)
        if params.get("query") and not params.get("url")
        else service.fetch(params)
    )
    if not result.get("ok"):
        raise RuntimeCapabilityError(
            str(
                result.get("error_message")
                or result.get("error_code")
                or "network fetch failed"
            )
        )
    return result


def project_test_arguments(params: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a fixed test request before asking for an execution grant."""
    if set(params) - {"profile", "target", "timeout_seconds"}:
        raise RuntimeCapabilityError("unknown project test parameters")
    profile = params.get("profile", "python-unittest")
    target = params.get("target", "tests")
    timeout = params.get("timeout_seconds", 30)
    if profile != "python-unittest" or not isinstance(target, str):
        raise RuntimeCapabilityError(
            "only the read-only python-unittest test profile is supported"
        )
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise RuntimeCapabilityError("timeout_seconds must be an integer from 1 to 300")
    path = Path(target.replace("\\", "/"))
    if len(target) > 1024 or "\0" in target or path.is_absolute() or ".." in path.parts:
        raise RuntimeCapabilityError("test target must remain workspace-relative")
    return {"profile": profile, "target": target, "timeout_seconds": timeout}


def _project_tests(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Consume the existing fixed Workbench test profile, never arbitrary argv."""
    from nous_runtime.workspace import DeveloperWorkbench
    from nous_runtime.evaluation.validators.test_validator import TestValidator

    request = project_test_arguments(params)
    result = DeveloperWorkbench(root).run_profile(
        request["profile"],
        target=request["target"],
        timeout_seconds=request["timeout_seconds"],
    )
    evidence = TestValidator(workspace=str(root)).validate(
        None, {"test_run_id": result["run_id"]}
    )[0]
    verification = {
        "test_framework": evidence.source,
        "test_outcome": evidence.detail.get("test_outcome", "UNKNOWN"),
        "test_counts": evidence.detail.get("test_counts"),
    }
    result = {
        **result,
        "execution_ok": result["ok"],
        "ok": result["ok"] and verification["test_outcome"] == "PASS",
        **verification,
    }
    from nous_runtime.artifact import (
        ContentAddressedArtifactStore,
        ArtifactManager,
        ArtifactRegistry,
        ArtifactType,
    )
    from nous_runtime.core.redaction import redact_sensitive_data

    store = ContentAddressedArtifactStore(root / ".nous" / "artifacts")
    stored = store.store_bytes(
        json.dumps(redact_sensitive_data(result), sort_keys=True).encode(),
        artifact_type="file",
        name="Project test result",
        media_type="application/json",
        produced_by="developer.workbench",
        metadata={"run_id": result["run_id"]},
    )["artifact"]
    location = store.resolve(stored["digest"], verify=True).relative_to(root).as_posix()
    artifact = ArtifactManager(
        ArtifactRegistry(root / ".nous" / "artifacts.jsonl")
    ).create(
        ArtifactType.FILE,
        "Project test result",
        location=location,
        creator="developer.workbench",
        metadata={"run_id": result["run_id"], "digest": stored["digest"]},
    )
    return {
        **result,
        "artifact_id": artifact.id,
        "artifact_digest": stored["digest"],
        "artifacts": {"test_result": artifact.id, "test_content": stored["digest"]},
    }


_EXECUTORS: dict[str, Callable[[Path, dict[str, Any]], dict[str, Any]]] = {
    "project.run_tests": _project_tests,
    "document.create": _document_create,
    "document.render": _document_render,
    "environment.create": _environment_create,
    "environment.start": _environment_lifecycle("start"),
    "environment.run": _environment_lifecycle("run"),
    "environment.stop": _environment_lifecycle("stop"),
    "environment.destroy": _environment_lifecycle("destroy"),
    "simulation.create": _simulation_create,
    "simulation.run": _simulation_run,
    "simulation.replay": _simulation_replay,
    "simulation.cancel": _simulation_cancel,
    "scientific.analyze": _scientific_analyze,
    "network.fetch": _network_fetch,
}


def supports_runtime_capability(capability_id: str) -> bool:
    return str(capability_id) in _EXECUTORS


def list_runtime_capabilities() -> tuple[str, ...]:
    return tuple(sorted(_EXECUTORS))


def execute_runtime_capability(
    capability_id: str,
    params: Mapping[str, Any] | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Execute one already-authorized built-in Runtime capability."""
    executor = _EXECUTORS.get(str(capability_id))
    if executor is None:
        raise RuntimeCapabilityError(
            f"Runtime capability is not implemented by the central dispatcher: {capability_id}"
        )
    result = executor(_workspace_root(workspace_root), dict(params or {}))
    if not isinstance(result, dict):
        raise RuntimeCapabilityError("Runtime capability returned an invalid result")
    return result


__all__ = [
    "RuntimeCapabilityError",
    "execute_runtime_capability",
    "list_runtime_capabilities",
    "supports_runtime_capability",
]
