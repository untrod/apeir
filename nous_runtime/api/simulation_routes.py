"""Simulation Workbench API over the governed reproducible Simulation Runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _runtime():
    from nous_runtime.simulations import SimulationRuntime

    root = (
        Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    )
    return SimulationRuntime(root)


def _error(exc: Exception) -> dict[str, Any]:
    from nous_runtime.simulations import SimulationNotFoundError

    code = (
        "NOUS_NOT_FOUND"
        if isinstance(exc, SimulationNotFoundError)
        else "NOUS_INVALID_REQUEST"
    )
    return err_response(code, str(exc))


def handle_simulation_status() -> dict[str, Any]:
    try:
        return ok_response(_runtime().status())
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulations() -> dict[str, Any]:
    try:
        simulations = _runtime().list_simulations()
        return ok_response({"simulations": simulations, "total": len(simulations)})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation(simulation_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().get(simulation_id))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_runs(
    simulation_id: str = "", limit: int | str = 100
) -> dict[str, Any]:
    try:
        runs = _runtime().list_runs(simulation_id=simulation_id, limit=int(limit))
        return ok_response({"runs": runs, "total": len(runs)})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_run_record(run_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().get_run(run_id))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_create(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("simulation.create", body, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_run(
    simulation_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        body = body or {}
        unknown = set(body) - {"replay_of"}
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        replay_of = str(body.get("replay_of") or "")
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("simulation.run", {"simulation_id": simulation_id, "replay_of": replay_of}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_replay(
    run_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        if body:
            raise ValueError("replay does not accept request fields")
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("simulation.replay", {"run_id": run_id}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_simulation_cancel(
    simulation_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        if body:
            raise ValueError("cancel does not accept request fields")
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("simulation.cancel", {"simulation_id": simulation_id}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def ensure_simulation_capabilities() -> tuple[str, ...]:
    from nous_runtime.capability import register_capability

    operations = {
        "simulation.create": (
            "Create a versioned reproducible Simulation contract",
            "local_write",
            "reversible",
            "medium",
        ),
        "simulation.run": (
            "Execute a bounded Simulation through EnvironmentRuntime",
            "local_write",
            "partially_reversible",
            "high",
        ),
        "simulation.replay": (
            "Replay a completed Simulation and verify numerical tolerance",
            "local_write",
            "reversible",
            "high",
        ),
        "simulation.cancel": (
            "Request cancellation of an active Simulation",
            "destructive",
            "irreversible",
            "high",
        ),
    }
    registered: list[str] = []
    for capability_id, (description, effect, reversibility, risk) in operations.items():
        registered.append(
            register_capability(
                capability_id,
                description=description,
                category="scientific-compute",
                provider="nous",
                risk=risk,
                timeout_ms=3_600_000,
                max_retries=0,
                requires_auth=True,
                requires_device=False,
                executor_type="runtime",
                side_effect_class=effect,
                reversibility=reversibility,
                model_uncertainty=0.0,
                idempotent=False,
                privileged=True,
                locality="local",
                connection_type="local-ipc",
                metadata={
                    "service": "nous_runtime.simulations.service:SimulationRuntime",
                    "operation": capability_id.rsplit(".", 1)[-1],
                    "simulation_contract": "nous.simulation/v1",
                    "simulation_run_contract": "nous.simulation-run/v1",
                    "execution_authority": "EnvironmentRuntime",
                    "event_authority": "EventStream",
                    "artifact_authority": "ArtifactRegistry",
                },
            )
        )
    return tuple(registered)


SIMULATION_ROUTES = {
    ("GET", "/api/v1/simulations/status"): handle_simulation_status,
    ("GET", "/api/v1/simulations"): handle_simulations,
    ("GET", "/api/v1/simulations/runs"): handle_simulation_runs,
    ("GET", "/api/v1/simulations/runs/{run_id}"): handle_simulation_run_record,
    ("GET", "/api/v1/simulations/{simulation_id}"): handle_simulation,
    ("POST", "/api/v1/simulations"): handle_simulation_create,
    ("POST", "/api/v1/simulations/{simulation_id}/run"): handle_simulation_run,
    ("POST", "/api/v1/simulations/runs/{run_id}/replay"): handle_simulation_replay,
    ("POST", "/api/v1/simulations/{simulation_id}/cancel"): handle_simulation_cancel,
}

SIMULATION_GOVERNANCE = {
    ("POST", "/api/v1/simulations"): (
        "simulation.create",
        "local_write",
        "reversible",
    ),
    ("POST", "/api/v1/simulations/{simulation_id}/run"): (
        "simulation.run",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/simulations/runs/{run_id}/replay"): (
        "simulation.replay",
        "local_write",
        "reversible",
    ),
    ("POST", "/api/v1/simulations/{simulation_id}/cancel"): (
        "simulation.cancel",
        "destructive",
        "irreversible",
    ),
}

ensure_simulation_capabilities()

__all__ = ["SIMULATION_GOVERNANCE", "SIMULATION_ROUTES"]
