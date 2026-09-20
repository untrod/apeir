"""Environment Inspector API over the governed Environment Runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _runtime():
    from nous_runtime.environments import EnvironmentRuntime

    root = Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    return EnvironmentRuntime(root)


def _error(exc: Exception) -> dict[str, Any]:
    from nous_runtime.environments import EnvironmentNotFoundError, EnvironmentProviderError

    if isinstance(exc, EnvironmentNotFoundError):
        code = "NOUS_NOT_FOUND"
    elif isinstance(exc, EnvironmentProviderError):
        code = "NOUS_PROVIDER_UNAVAILABLE"
    else:
        code = "NOUS_INVALID_REQUEST"
    return err_response(code, str(exc))


def handle_environment_status() -> dict[str, Any]:
    try:
        return ok_response(_runtime().status())
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environments() -> dict[str, Any]:
    try:
        environments = _runtime().list_environments()
        return ok_response({"environments": environments, "total": len(environments)})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment(environment_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().get(environment_id))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_create(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("environment.create", body, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_start(environment_id: str) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("environment.start", {"environment_id": environment_id}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_run(environment_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("environment.run", {"environment_id": environment_id, **body}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_stop(environment_id: str) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("environment.stop", {"environment_id": environment_id}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_destroy(environment_id: str) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("environment.destroy", {"environment_id": environment_id}, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_environment_logs(environment_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().logs(environment_id))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def ensure_environment_capabilities() -> tuple[str, ...]:
    from nous_runtime.capability import register_capability

    operations = {
        "environment.create": ("Create a bounded ExecutionEnvironment contract", "local_write", "reversible", "medium"),
        "environment.start": ("Prepare and start an environment through its provider", "external_write", "partially_reversible", "high"),
        "environment.run": ("Run an argv command inside a ready environment", "local_write", "partially_reversible", "high"),
        "environment.stop": ("Stop a running environment and its process tree", "destructive", "reversible", "high"),
        "environment.destroy": ("Destroy provider state for an environment", "destructive", "irreversible", "critical"),
    }
    registered: list[str] = []
    for capability_id, (description, effect, reversibility, risk) in operations.items():
        registered.append(
            register_capability(
                capability_id,
                description=description,
                category="execution",
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
                    "service": "nous_runtime.environments.service:EnvironmentRuntime",
                    "operation": capability_id.rsplit(".", 1)[-1],
                    "environment_contract": "nous.environment/v1",
                    "provider_contract": "nous.environment-provider/v1",
                    "event_authority": "EventStream",
                    "artifact_authority": "ArtifactRegistry",
                },
            )
        )
    return tuple(registered)


ENVIRONMENT_ROUTES = {
    ("GET", "/api/v1/environments/status"): handle_environment_status,
    ("GET", "/api/v1/environments"): handle_environments,
    ("GET", "/api/v1/environments/{environment_id}"): handle_environment,
    ("GET", "/api/v1/environments/{environment_id}/logs"): handle_environment_logs,
    ("POST", "/api/v1/environments"): handle_environment_create,
    ("POST", "/api/v1/environments/{environment_id}/start"): handle_environment_start,
    ("POST", "/api/v1/environments/{environment_id}/run"): handle_environment_run,
    ("POST", "/api/v1/environments/{environment_id}/stop"): handle_environment_stop,
    ("DELETE", "/api/v1/environments/{environment_id}"): handle_environment_destroy,
}

ENVIRONMENT_GOVERNANCE = {
    ("POST", "/api/v1/environments"): ("environment.create", "local_write", "reversible"),
    ("POST", "/api/v1/environments/{environment_id}/start"): (
        "environment.start",
        "external_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/environments/{environment_id}/run"): (
        "environment.run",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/environments/{environment_id}/stop"): (
        "environment.stop",
        "destructive",
        "reversible",
    ),
    ("DELETE", "/api/v1/environments/{environment_id}"): (
        "environment.destroy",
        "destructive",
        "irreversible",
    ),
}

ensure_environment_capabilities()

__all__ = ["ENVIRONMENT_GOVERNANCE", "ENVIRONMENT_ROUTES"]
