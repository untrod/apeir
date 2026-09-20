"""Canonical dispatcher for built-in Runtime service capabilities.

Model inference is submitted through NKI. These bounded local services execute
in the Python Runtime after authorization and never claim Rust Kernel effects.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping


class RuntimeCapabilityError(ValueError):
    """A Runtime capability cannot be dispatched with the supplied request."""


def _workspace_root(value: str | Path | None = None) -> Path:
    root = Path(value or os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
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
    return DocumentRuntime(root).render(_required_text(params, "document_id"), list(formats))


def _environment_create(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.environments import EnvironmentRuntime
    return EnvironmentRuntime(root).create(params)


def _environment_lifecycle(operation: str) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
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
    return SimulationRuntime(root).run(_required_text(params, "simulation_id"), replay_of=str(params.get("replay_of") or ""))


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
    result = service.search(params) if params.get("query") and not params.get("url") else service.fetch(params)
    if not result.get("ok"):
        raise RuntimeCapabilityError(str(result.get("error_message") or result.get("error_code") or "network fetch failed"))
    return result


_EXECUTORS: dict[str, Callable[[Path, dict[str, Any]], dict[str, Any]]] = {
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


def execute_runtime_capability(capability_id: str, params: Mapping[str, Any] | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    """Execute one already-authorized built-in Runtime capability."""
    executor = _EXECUTORS.get(str(capability_id))
    if executor is None:
        raise RuntimeCapabilityError(f"Runtime capability is not implemented by the central dispatcher: {capability_id}")
    result = executor(_workspace_root(workspace_root), dict(params or {}))
    if not isinstance(result, dict):
        raise RuntimeCapabilityError("Runtime capability returned an invalid result")
    return result


__all__ = ["RuntimeCapabilityError", "execute_runtime_capability", "list_runtime_capabilities", "supports_runtime_capability"]
