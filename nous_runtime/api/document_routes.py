"""Document Workbench API over the governed Document Runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _runtime():
    from nous_runtime.documents import DocumentRuntime

    root = Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    return DocumentRuntime(root)


def _error(exc: Exception) -> dict[str, Any]:
    from nous_runtime.documents.service import DocumentNotFoundError

    code = "NOUS_NOT_FOUND" if isinstance(exc, DocumentNotFoundError) else "NOUS_INVALID_REQUEST"
    return err_response(code, str(exc))


def handle_document_status() -> dict[str, Any]:
    try:
        return ok_response(_runtime().status())
    except (OSError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_documents() -> dict[str, Any]:
    try:
        documents = _runtime().list_documents()
        return ok_response({"documents": documents, "total": len(documents)})
    except (OSError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_document(document_id: str) -> dict[str, Any]:
    try:
        return ok_response(_runtime().get(document_id))
    except (OSError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_document_create(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability("document.create", body, workspace_root=_runtime().root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def handle_document_render(document_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        formats = body.get("formats") or ["docx", "pdf"]
        if not isinstance(formats, list):
            raise ValueError("formats must be an array")
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        return ok_response(execute_runtime_capability(
            "document.render", {"document_id": document_id, "formats": formats}, workspace_root=_runtime().root
        ))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(exc)


def ensure_document_capabilities() -> tuple[str, str]:
    from nous_runtime.capability import register_capability

    common = {
        "category": "productivity",
        "provider": "nous",
        "risk": "medium",
        "timeout_ms": 120000,
        "max_retries": 0,
        "requires_auth": True,
        "requires_device": False,
        "executor_type": "runtime",
        "side_effect_class": "local_write",
        "reversibility": "reversible",
        "model_uncertainty": 0.0,
        "idempotent": False,
        "privileged": True,
        "locality": "local",
        "connection_type": "none",
    }
    create = register_capability(
        "document.create",
        description="Create bounded versioned Document IR in the active workspace",
        metadata={"service": "nous_runtime.documents.service:DocumentRuntime", "operation": "create", "event_authority": "EventStream", "artifact_authority": "ArtifactRegistry"},
        **common,
    )
    render = register_capability(
        "document.render",
        description="Render and structurally verify DOCX/PDF artifacts from Document IR",
        metadata={"service": "nous_runtime.documents.service:DocumentRuntime", "operation": "render", "formats": ["docx", "pdf"], "event_authority": "EventStream", "artifact_authority": "ArtifactRegistry"},
        **common,
    )
    return create, render


DOCUMENT_ROUTES = {
    ("GET", "/api/v1/documents/status"): handle_document_status,
    ("GET", "/api/v1/documents"): handle_documents,
    ("GET", "/api/v1/documents/{document_id}"): handle_document,
    ("POST", "/api/v1/documents"): handle_document_create,
    ("POST", "/api/v1/documents/{document_id}/render"): handle_document_render,
}

DOCUMENT_GOVERNANCE = {
    ("POST", "/api/v1/documents"): ("document.create", "local_write", "reversible"),
    ("POST", "/api/v1/documents/{document_id}/render"): ("document.render", "local_write", "reversible"),
}

ensure_document_capabilities()

__all__ = ["DOCUMENT_GOVERNANCE", "DOCUMENT_ROUTES"]
