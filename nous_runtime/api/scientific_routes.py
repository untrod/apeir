"""Authenticated API for the governed Scientific Capability Layer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _runtime():
    from nous_runtime.scientific import ScientificRuntime

    root = (
        Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    )
    return ScientificRuntime(root)


def _error(exc: Exception) -> dict[str, Any]:
    from nous_runtime.scientific import ScientificNotFoundError

    code = (
        "NOUS_NOT_FOUND"
        if isinstance(exc, ScientificNotFoundError)
        else "NOUS_INVALID_REQUEST"
    )
    return err_response(code, str(exc))


def handle_scientific_status() -> dict[str, Any]:
    try:
        return ok_response(_runtime().status())
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_scientific_analyses() -> dict[str, Any]:
    try:
        analyses = _runtime().list_analyses()
        return ok_response({"analyses": analyses, "total": len(analyses)})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_scientific_analysis(analysis_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().get(analysis_id))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_scientific_analyze(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("scientific.analyze", body, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def ensure_scientific_capability() -> str:
    from nous_runtime.capability import register_capability

    return register_capability(
        "scientific.analyze",
        description=(
            "Analyze a governed Simulation with qualified scientific providers "
            "and produce Claim/Evidence plus verified DOCX/PDF reports"
        ),
        category="scientific-compute",
        provider="nous",
        risk="high",
        timeout_ms=900_000,
        max_retries=0,
        requires_auth=True,
        requires_device=False,
        executor_type="runtime",
        side_effect_class="local_write",
        reversibility="reversible",
        model_uncertainty=0.0,
        idempotent=False,
        privileged=True,
        locality="local",
        connection_type="local-ipc",
        metadata={
            "service": "nous_runtime.scientific.service:ScientificRuntime",
            "analysis_contract": "nous.scientific-analysis/v1",
            "result_contract": "nous.scientific-result/v1",
            "execution_authority": "EnvironmentRuntime",
            "claim_authority": "ClaimEvidenceGraph",
            "document_authority": "DocumentRuntime",
            "event_authority": "EventStream",
            "artifact_authority": "ArtifactRegistry",
        },
    )


SCIENTIFIC_ROUTES = {
    ("GET", "/api/v1/scientific/status"): handle_scientific_status,
    ("GET", "/api/v1/scientific/analyses"): handle_scientific_analyses,
    ("GET", "/api/v1/scientific/analyses/{analysis_id}"): handle_scientific_analysis,
    ("POST", "/api/v1/scientific/analyses"): handle_scientific_analyze,
}

SCIENTIFIC_GOVERNANCE = {
    ("POST", "/api/v1/scientific/analyses"): (
        "scientific.analyze",
        "local_write",
        "reversible",
    ),
}

ensure_scientific_capability()

__all__ = ["SCIENTIFIC_GOVERNANCE", "SCIENTIFIC_ROUTES"]
