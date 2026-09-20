"""
Enhanced health and status endpoints for the Nous Runtime API.

Provides comprehensive status information for desktop bootstrap,
workspace management, provider configuration, and session handling.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def handle_health_detailed() -> dict[str, Any]:
    """Comprehensive health check returning runtime, workspace, and provider status."""
    try:
        import nous_runtime

        # Runtime status
        runtime_version = nous_runtime.__version__
        from nous_runtime.api.kernel_status import kernel_status
        kernel = kernel_status()
        runtime_ready = not kernel["configured"] or kernel["ready"]
        # Reaching this handler proves the Runtime API service is live. A newly
        # constructed Runtime() would only be an unrelated process-local view.
        runtime_running = True

        # Workspace status
        workspace_available = False
        workspace_path = ""
        try:
            workspace_root = os.environ.get("NOUS_WORKSPACE_ROOT", "")
            if workspace_root and os.path.isdir(workspace_root):
                workspace_available = True
                workspace_path = workspace_root
        except Exception:
            pass

        # Provider status
        provider_configured = False
        provider_count = 0
        try:
            from nous_runtime.services.providers import list_provider_summaries
            providers = list_provider_summaries()
            if isinstance(providers, dict):
                provider_list = providers.get("providers", providers.get("data", []))
            elif isinstance(providers, list):
                provider_list = providers
            else:
                provider_list = []
            provider_count = len(provider_list) if isinstance(provider_list, list) else 0
            provider_configured = provider_count > 0
        except Exception:
            pass

        # Session check
        session_required = True
        try:
            token = os.environ.get("NOUS_API_TOKEN") or os.environ.get("NOUS_AUTH_TOKEN")
            if token:
                session_required = False
        except Exception:
            pass

        return ok_response({
            "runtime_version": runtime_version,
            "status": "ok" if runtime_ready else "degraded",
            "ready": runtime_ready and runtime_running,
            "running": runtime_running,
            "workspace_available": workspace_available,
            "workspace_path": workspace_path,
            "provider_configured": provider_configured,
            "provider_count": provider_count,
            "intelligence_mode": (
                "disabled"
                if os.environ.get("NOUS_NO_INTELLIGENCE", "").strip().lower()
                in {"1", "true", "yes", "on"}
                else "enabled"
            ),
            "session_required": session_required,
            "platform": sys.platform,
            "architecture": platform.machine(),
            "python_version": sys.version,
            "kernel": kernel,
        })
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_live() -> dict[str, Any]:
    """Liveness check for the HTTP process; it does not inspect providers."""
    return ok_response({"alive": True, "pid": os.getpid()})

def handle_ready() -> dict[str, Any]:
    """Readiness of the API and its configured Rust Kernel dependency."""
    from nous_runtime.api.kernel_status import kernel_status
    kernel = kernel_status()
    return ok_response({
        "ready": not kernel["configured"] or kernel["ready"],
        "api_alive": True,
        "kernel": kernel,
        "timestamp": __import__("time").time(),
    })


def handle_runtime_status() -> dict[str, Any]:
    """Extended runtime status including gateway and router state."""
    try:
        import nous_runtime
        from nous_runtime.api.kernel_status import kernel_status
        kernel = kernel_status()
        from nous_runtime.capability.availability import check_availability
        availability = check_availability()
        capability_availability = availability["summary"]

        # Additional gateway info
        gateway_configured = False
        router_ready = False
        model_count = 0
        try:
            from nous_runtime.model_runtime.factory import gateway_service
            gateway = gateway_service.gateway
            if gateway:
                gateway_configured = True
                router_ready = gateway.router is not None
                model_count = len(gateway.registry.list_models()) if gateway.registry else 0
        except Exception:
            try:
                from nous_runtime.model_runtime.center import ModelCenterService
                root = os.environ.get("NOUS_WORKSPACE_ROOT") or os.getcwd()
                snapshot = ModelCenterService(root).snapshot()
                model_count = int(snapshot.get("summary", {}).get("enabled", 0))
                gateway_configured = model_count > 0
                router_ready = model_count > 0
            except Exception:
                pass

        return ok_response({
            "version": nous_runtime.__version__,
            # Match /api/v1/status: this handler executes inside the live API
            # process, while Runtime() above is a fresh process-local view.
            "running": True,
            "providers": 0,
            "capabilities": capability_availability.get("registered", 0),
            "capability_availability": capability_availability,
            "packs": 0,
            "devices": 0,
            "events_total": 0,
            "jobs_pending": 0,
            "demo_mode": False,
            "errors": [kernel["error"]] if kernel.get("error") else [],
            "gateway_configured": gateway_configured,
            "router_ready": router_ready,
            "model_count": model_count,
            "platform": sys.platform,
            "architecture": platform.machine(),
            "kernel": kernel,
            "execution_authorities": {
                "model_inference": "rust-kernel-nki",
                "local_effects": "python-runtime-services",
            },
        })
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_workspace_status() -> dict[str, Any]:
    """Workspace status — existence, path, validity."""
    try:
        workspace_root = os.environ.get("NOUS_WORKSPACE_ROOT", "")
        exists = bool(workspace_root and os.path.isdir(workspace_root))
        valid = exists

        # Check for required structure
        if exists:
            required_dirs = ["artifacts", "conversations", "tasks", "logs", "cache"]
            for d in required_dirs:
                if not os.path.isdir(os.path.join(workspace_root, d)):
                    valid = False
                    break

        return ok_response({
            "exists": exists,
            "path": workspace_root,
            "valid": valid,
            "writable": os.access(workspace_root, os.W_OK) if exists else False,
        })
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_provider_status() -> dict[str, Any]:
    """Provider configuration status — count, health, configured."""
    try:
        from nous_runtime.services.providers import list_provider_summaries, provider_health_summary

        summaries = list_provider_summaries()
        if isinstance(summaries, dict):
            provider_list = summaries.get("providers", summaries.get("data", []))
        elif isinstance(summaries, list):
            provider_list = summaries
        else:
            provider_list = []

        count = len(provider_list) if isinstance(provider_list, list) else 0

        health = {}
        try:
            health = provider_health_summary()
        except Exception:
            pass

        return ok_response({
            "configured": count > 0,
            "count": count,
            "providers": [
                {
                    "id": p.get("id", p.get("provider_id", "")),
                    "name": p.get("name", p.get("display_name", "")),
                    "type": p.get("type", p.get("service_type", "")),
                    "enabled": p.get("enabled", True),
                }
                for p in (provider_list if isinstance(provider_list, list) else [])
            ],
            "health": health,
        })
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_session_refresh(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh or establish a local session token."""
    try:
        from nous_runtime.control_plane.auth import ControlPlaneAuth

        auth = ControlPlaneAuth.get()
        # Revoke existing and generate new
        auth.revoke()
        token = auth.generate()

        # Return token fingerprint only (never the full token in JSON)
        fingerprint = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"

        return ok_response({
            "session_established": True,
            "token_fingerprint": fingerprint,
            "token_file": auth.token_file,
        })
    except Exception as e:
        return err_response("SESSION_REFRESH_ERROR", str(e))
