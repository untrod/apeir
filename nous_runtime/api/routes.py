# -*- coding: utf-8 -*-
"""
APEIR Distribution API v1 - unified REST API routes.

All surfaces (CLI, Web, Desktop, Mobile) call these endpoints.
No surface has its own database. No surface has its own state.

Base URL: /api/v1

Endpoints:
    GET  /status               Runtime status
    GET  /health                Health check
    GET  /version               Version info

    GET  /capabilities          List capabilities
    POST /capabilities/run      Execute a capability

    GET  /providers             List providers
    GET  /providers/health      Provider health aggregation

    GET  /packs                 List installed packs
    POST /packs/install         Install a pack
    DELETE /packs/{name}        Remove a pack

    GET  /jobs                  List jobs
    GET  /jobs/{id}             Get job detail

    GET  /traces                Recent execution traces
    GET  /traces/{id}           Trace detail

    GET  /experience/stats      Experience statistics

    GET  /objects               List runtime objects
    GET  /objects/{kind}/{id}   Get object detail
"""

from __future__ import annotations

import hmac
import inspect
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from nous_runtime.api.responses import err_response, ok_response

log = logging.getLogger("nous.api")


PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/version"),
    ("GET", "/live"),
    ("GET", "/ready"),
    ("GET", "/api/v1/health/detailed"),
    ("GET", "/api/v1/runtime/status"),
    ("GET", "/api/v1/workspace/status"),
    ("GET", "/api/v1/provider/status"),
    ("POST", "/api/v1/session/refresh"),
}
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _extract_bearer(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _authentication_context(auth: dict[str, Any] | None, *, surface: str):
    if not auth or auth.get("query_token"):
        return None
    token = str(auth.get("token") or "")
    headers = auth.get("headers") or {}
    if not token and isinstance(headers, dict):
        token = str(headers.get("x-auth-token") or headers.get("X-Auth-Token") or "")
        if not token:
            token = _extract_bearer(
                str(headers.get("authorization") or headers.get("Authorization") or "")
            )
    configured = os.environ.get("NOUS_API_TOKEN") or os.environ.get("NOUS_AUTH_TOKEN")
    if not configured or not token or not hmac.compare_digest(token, configured):
        return None

    from nous_runtime.governance.contracts import AuthorizationContext

    return AuthorizationContext(
        subject_type="service",
        subject_id=os.environ.get("NOUS_API_SUBJECT", "api-service"),
        authn_method="api_bearer_token",
        authn_confidence=0.9,
        session_locality=(
            "local"
            if bool(auth.get("loopback"))
            or surface not in {"server", "api", "control_plane"}
            else "remote"
        ),
    )


def _is_authenticated(
    auth: dict[str, Any] | None, *, surface: str = "local_cli"
) -> bool:
    return _authentication_context(auth, surface=surface) is not None


def _auth_required(method: str, path: str, *, surface: str = "local_cli") -> bool:
    method = method.upper()
    if (method, path) in PUBLIC_ROUTES:
        return False
    if method in MUTATION_METHODS:
        return True
    from nous_runtime.governance.runtime_mode import should_fail_closed

    return should_fail_closed(surface=surface)


def _authorize_api_request(
    method: str,
    path: str,
    auth: dict[str, Any] | None,
    *,
    surface: str = "local_cli",
) -> dict[str, Any] | None:
    if not _auth_required(method, path, surface=surface):
        return None
    if _is_authenticated(auth, surface=surface):
        return None
    return err_response(
        "NOUS_UNAUTHENTICATED",
        "Authentication required",
        {"path": path, "method": method.upper()},
    )


# Status


def handle_status() -> dict[str, Any]:
    try:
        import nous_runtime
        from nous_runtime.runtime.lifecycle import Runtime
        from nous_runtime.services.packs import count_packs
        from nous_runtime.api.kernel_status import kernel_status

        r = Runtime()
        s = r.status()
        from nous_runtime.capability.availability import check_availability

        capability_availability = check_availability()["summary"]
        try:
            from nous_runtime.services.providers import list_providers

            providers = len(list_providers())
        except Exception:
            providers = s.providers
        return ok_response(
            {
                "version": nous_runtime.__version__,
                # Reaching this handler proves that the Runtime API process is live.
                # Kernel Runtime() state is process-local and is not an API liveness
                # signal when the desktop sidecar owns the service lifecycle.
                "running": True,
                "providers": providers,
                "capabilities": capability_availability.get("registered", s.capabilities),
                "capability_availability": capability_availability,
                "packs": count_packs(),
                "devices": s.devices,
                "events": s.events_total,
                "jobs_pending": s.jobs_pending,
                "demo_mode": s.demo_mode,
                "kernel": kernel_status(),
                "execution_authorities": {
                    "model_inference": "rust-kernel-nki",
                    "local_effects": "python-runtime-services",
                },
            }
        )
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_health() -> dict[str, Any]:
    try:
        from nous_runtime.services.providers import provider_health_summary

        return ok_response(provider_health_summary())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_version() -> dict[str, Any]:
    from nous_runtime import __version__

    return ok_response({"version": __version__})


def handle_usage_summary(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return local model usage without exposing credential values."""
    try:
        from nous_runtime.model_runtime.cost_control import CostController

        selected_day = str((params or {}).get("day") or "").strip() or None
        return ok_response(CostController.from_environment().summary(day=selected_day))
    except Exception as exc:
        return err_response("NOUS_INTERNAL_ERROR", str(exc))


# Capabilities


def handle_list_capabilities() -> dict[str, Any]:
    try:
        from nous_runtime.services.capabilities import list_capabilities

        return ok_response(list_capabilities())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_run_capability(
    body: dict,
    *,
    authorization_context=None,
    governance_surface: str = "local_cli",
) -> dict[str, Any]:
    capability_id = body.get("capability_id", "")
    params = body.get("params", {})
    if not capability_id:
        return err_response("NOUS_INVALID_REQUEST", "capability_id is required")
    if not isinstance(params, dict):
        return err_response("NOUS_INVALID_REQUEST", "params must be an object")
    reserved = {"_authorization_context", "_governance_surface"} & set(params)
    if reserved:
        return err_response(
            "NOUS_INVALID_REQUEST", "reserved execution parameters are not allowed"
        )

    from nous_runtime.capability.resolver import execute_capability

    result = execute_capability(
        capability_id,
        _authorization_context=authorization_context,
        _governance_surface=governance_surface,
        **params,
    )
    return ok_response(
        {
            "ok": result.ok,
            "capability_id": result.capability_id,
            "provider_id": result.provider_id,
            "result": result.result,
            "error": result.error,
            "error_code": result.error_code,
            "duration_ms": result.duration_ms,
        }
    )


# Providers


def handle_list_providers() -> dict[str, Any]:
    try:
        from nous_runtime.services.providers import list_provider_summaries

        return ok_response(list_provider_summaries())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_provider_health() -> dict[str, Any]:
    try:
        from nous_runtime.services.providers import provider_health_summary

        return ok_response(provider_health_summary())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Packs


def handle_list_packs() -> dict[str, Any]:
    try:
        from nous_runtime.services.packs import list_packs

        return ok_response(list_packs())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_install_pack(body: dict) -> dict[str, Any]:
    path = body.get("path", "")
    if not path:
        return err_response("NOUS_INVALID_REQUEST", "path is required")
    try:
        from nous_runtime.services.packs import install_pack

        return ok_response(install_pack(path))
    except Exception as e:
        return err_response("NOUS_EXECUTION_FAILED", str(e))


def handle_remove_pack(name: str) -> dict[str, Any]:
    try:
        from nous_runtime.services.packs import remove_pack

        remove_pack(name)
        return ok_response({"removed": name})
    except Exception as e:
        return err_response("NOUS_EXECUTION_FAILED", str(e))


# Jobs


def handle_list_jobs(status_filter: str = "") -> dict[str, Any]:
    try:
        from nous_runtime.services.jobs import list_jobs

        if status_filter:
            return ok_response(list_jobs(status=status_filter))
        return ok_response(list_jobs())
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_get_job(job_id: str) -> dict[str, Any]:
    try:
        from nous_runtime.services.jobs import get_job

        job = get_job(job_id)
        if job:
            return ok_response(job)
        return err_response("NOUS_CAPABILITY_NOT_FOUND", f"Job {job_id} not found")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Traces


def handle_list_traces(limit: int = 20, session_id: str = "") -> dict[str, Any]:
    try:
        from nous_runtime.services.traces import get_recent_traces, get_session_traces

        if session_id:
            return ok_response(get_session_traces(session_id))
        return ok_response(get_recent_traces(limit))
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Nodes API


def handle_list_nodes(status: str = "") -> dict[str, Any]:
    """List registered nodes with optional status filter."""
    try:
        from nous_runtime.connectivity.control_plane.node_registry import NodeRegistry
        from nous_runtime.connectivity.control_plane.session_registry import (
            SessionRegistry,
        )

        nodes = NodeRegistry.list_all()
        sessions = {s.node_id: s.to_dict() for s in SessionRegistry().list_active()}

        result = []
        for node in nodes:
            node_id = node.get("node_id", "")
            session = sessions.get(node_id, {})
            result.append(
                {
                    "node_id": node_id,
                    "node_name": node.get("node_name", ""),
                    "platform": node.get("platform_os", ""),
                    "arch": node.get("platform_arch", ""),
                    "capabilities": node.get("capabilities", []),
                    "online": session.get("status") == "active",
                    "last_seen": session.get(
                        "last_heartbeat", node.get("registered_at", "")
                    ),
                    "status": "online"
                    if session.get("status") == "active"
                    else "offline",
                }
            )

        if status:
            result = [n for n in result if n["status"] == status]

        return ok_response(result)
    except ImportError:
        return ok_response([])
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_get_node(node_id: str) -> dict[str, Any]:
    """Get node details by ID."""
    try:
        from nous_runtime.connectivity.control_plane.node_registry import NodeRegistry

        node = NodeRegistry.get(node_id)
        if node is None:
            return err_response("NOT_FOUND", f"Node '{node_id}' not found")
        return ok_response(node)
    except ImportError:
        return err_response("NOT_AVAILABLE", "Node registry not available")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_scan_nodes() -> dict[str, Any]:
    """Scan network for available nodes."""
    try:
        from nous_runtime.connectivity.control_plane.gateway import ControlPlaneGateway

        gateway = ControlPlaneGateway()
        status = gateway.get_status()
        return ok_response(
            {
                "nodes_found": status.get("known_nodes", 0),
                "nodes_online": status.get("connected_nodes", 0),
                "status": status,
            }
        )
    except ImportError:
        return err_response("NOT_AVAILABLE", "Control plane not available")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Artifacts API


def handle_list_artifacts(task_id: str = "", limit: int = 50) -> dict[str, Any]:
    """List artifacts, optionally filtered by task."""
    try:
        # Collect artifacts from active tasks
        artifacts = []
        if task_id:
            # Return artifacts for a specific task from its result
            return ok_response({"task_id": task_id, "artifacts": artifacts})
        return ok_response({"artifacts": artifacts, "count": len(artifacts)})
    except ImportError:
        return ok_response({"artifacts": [], "count": 0})
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_get_artifact(artifact_id: str) -> dict[str, Any]:
    """Get artifact by ID."""
    try:
        return ok_response(
            {
                "artifact_id": artifact_id,
                "status": "available",
                "note": "Artifact retrieval available via task artifacts endpoint",
            }
        )
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Approvals API


def handle_approval_action(request_id: str, action: str) -> dict[str, Any]:
    """Approve or deny an approval request."""
    if action not in ("approve", "deny"):
        return err_response(
            "INVALID_ACTION", f"Action must be 'approve' or 'deny', got '{action}'"
        )

    try:
        from nous_runtime.governance.broker import get_broker

        broker = get_broker()

        if action == "approve":
            response = broker.approve(
                request_id,
                approver_id="api",
                reason="Approved via API",
            )
        else:
            response = broker.deny(
                request_id,
                approver_id="api",
                reason="Denied via API",
            )

        return ok_response(
            {
                "request_id": request_id,
                "action": action,
                "response": response.to_dict()
                if hasattr(response, "to_dict")
                else str(response),
            }
        )
    except ImportError:
        return err_response("NOT_AVAILABLE", "Approval broker not available")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Events API (SSE streaming)


def handle_events_stream(
    domain: str = "",
    since_event_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Get runtime events for SSE streaming consumption.

    Returns events since the given event_id, or recent events.
    Clients poll this endpoint with the last received event_id.
    """
    try:
        from nous_runtime.events.bus import get_event_bus

        bus = get_event_bus()
        events = bus.stream_events(
            domain=domain,
            since_event_id=since_event_id,
            limit=min(int(limit), 500),
        )
        return ok_response(
            {
                "events": events,
                "count": len(events),
                "domain": domain,
                "latest_event_id": events[-1]["event_id"] if events else "",
            }
        )
    except ImportError:
        return ok_response(
            {"events": [], "count": 0, "domain": domain, "latest_event_id": ""}
        )
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Model Observations API


def handle_model_observations(
    model_id: str = "",
    provider_id: str = "",
    capability_id: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Query model execution observations."""
    try:
        from nous_runtime.model_runtime.observation_store import get_observation_store

        store = get_observation_store()
        observations = store.query(
            model_id=model_id,
            provider_id=provider_id,
            capability_id=capability_id,
            limit=min(int(limit), 500),
        )
        stats = store.get_statistics()
        return ok_response(
            {
                "observations": observations,
                "count": len(observations),
                "statistics": stats,
            }
        )
    except ImportError:
        return ok_response({"observations": [], "count": 0, "statistics": {}})
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_model_rankings(
    capability_id: str = "",
    task_type: str = "",
    metric: str = "success_rate",
    min_samples: int = 10,
) -> dict[str, Any]:
    """Get model performance rankings."""
    try:
        from nous_runtime.model_runtime.observation_store import get_observation_store

        store = get_observation_store()
        rankings = store.get_model_rankings(
            capability_id=capability_id,
            task_type=task_type,
            metric=metric,
            min_samples=min(int(min_samples), 1),
        )
        return ok_response({"rankings": rankings, "count": len(rankings)})
    except ImportError:
        return ok_response({"rankings": [], "count": 0})
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Execution Traces API


def handle_get_trace(trace_id: str) -> dict[str, Any]:
    """Get a complete execution trace by ID."""
    try:
        from nous_runtime.execution.trace import get_tracer

        tracer = get_tracer()
        trace = tracer.get_trace(trace_id)
        if trace is None:
            return err_response("NOT_FOUND", f"Trace '{trace_id}' not found")
        return ok_response(trace.to_dict())
    except ImportError:
        return err_response("NOT_AVAILABLE", "Execution tracer not available")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def handle_trace_timeline(trace_id: str) -> dict[str, Any]:
    """Get chronological timeline of spans for a trace."""
    try:
        from nous_runtime.execution.trace import get_tracer

        tracer = get_tracer()
        timeline = tracer.get_trace_timeline(trace_id)
        stats = tracer.get_trace_statistics()
        return ok_response(
            {
                "trace_id": trace_id,
                "spans": timeline,
                "count": len(timeline),
                "global_statistics": stats,
            }
        )
    except ImportError:
        return err_response("NOT_AVAILABLE", "Execution tracer not available")
    except Exception as e:
        return err_response("NOUS_INTERNAL_ERROR", str(e))


# Experience


def handle_experience_stats(
    provider_id: str = "", capability_id: str = ""
) -> dict[str, Any]:
    from nous_runtime.learning.experience import stats

    return ok_response(stats(provider_id=provider_id, capability_id=capability_id))


def _inspector_snapshot_dict() -> dict[str, Any]:
    from nous_runtime.inspector import diagnose, snapshot

    snap = snapshot()
    snap.findings = diagnose(snap)
    return snap.to_dict()


def handle_inspector_runtime() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["runtime"])


def handle_inspector_capabilities() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["capabilities"])


def handle_inspector_tasks() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["tasks"])


def handle_inspector_observations() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["observations"])


def handle_inspector_memory() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["memory"])


def handle_inspector_diagnostics() -> dict[str, Any]:
    return ok_response(_inspector_snapshot_dict()["findings"])


def handle_inspector_checkpoints(
    limit: int = 20,
    keep_latest_per_task: int = 20,
) -> dict[str, Any]:
    from nous_runtime.checkpoint import CheckpointStoreError
    from nous_runtime.inspector import checkpoint_report

    try:
        maximum = int(limit)
        keep_latest = int(keep_latest_per_task)
        if not 1 <= maximum <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 1 <= keep_latest <= 10_000:
            raise ValueError("keep_latest_per_task must be between 1 and 10000")
        return ok_response(
            checkpoint_report(
                limit=maximum,
                keep_latest_per_task=keep_latest,
            )
        )
    except (TypeError, ValueError, CheckpointStoreError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_inspector_checkpoint_retention(
    body: dict[str, Any],
) -> dict[str, Any]:
    from nous_runtime.checkpoint import CheckpointStoreError
    from nous_runtime.inspector import apply_checkpoint_retention

    try:
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        keep_latest = int(body.get("keep_latest_per_task", 20))
        plan_digest = str(body.get("expected_plan_digest") or "")
        return ok_response(
            apply_checkpoint_retention(
                keep_latest_per_task=keep_latest,
                expected_plan_digest=plan_digest,
            )
        )
    except (TypeError, ValueError, CheckpointStoreError) as exc:
        return err_response(
            "NOUS_CHECKPOINT_RETENTION_REJECTED",
            str(exc),
        )


def handle_inspector_decisions(limit: int = 20) -> dict[str, Any]:
    from nous_runtime.intelligence import DecisionHistory
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        return ok_response([])
    return ok_response(
        [
            decision.to_dict()
            for decision in DecisionHistory(workspace).list(limit=limit)
        ]
    )


def _inspector_decision(decision_id: str):
    from nous_runtime.intelligence import DecisionHistory
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        return None
    return DecisionHistory(workspace).get(decision_id)


def handle_inspector_decision_candidates(decision_id: str) -> dict[str, Any]:
    decision = _inspector_decision(decision_id)
    if decision is None:
        return ok_response([])
    return ok_response([candidate.to_dict() for candidate in decision.candidates])


def handle_inspector_decision_ranking(decision_id: str) -> dict[str, Any]:
    decision = _inspector_decision(decision_id)
    if decision is None:
        return ok_response([])
    return ok_response(
        [
            {
                "candidate_id": candidate.candidate_id,
                "score": candidate.score,
                "rank": idx + 1,
            }
            for idx, candidate in enumerate(
                sorted(
                    decision.candidates,
                    key=lambda item: (-item.score, item.candidate_id),
                )
            )
        ]
    )


def handle_inspector_decision_constraints(decision_id: str) -> dict[str, Any]:
    decision = _inspector_decision(decision_id)
    if decision is None:
        return ok_response([])
    return ok_response([item.__dict__ for item in decision.rejected_candidates])


def handle_inspector_decision_score(decision_id: str) -> dict[str, Any]:
    decision = _inspector_decision(decision_id)
    if decision is None:
        return ok_response([])
    return ok_response([item.__dict__ for item in decision.score_breakdown])


def handle_inspector_outcomes(limit: int = 20, decision_id: str = "") -> dict[str, Any]:
    from nous_runtime.intelligence import JsonlDecisionStore
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    if workspace is None:
        return ok_response([])
    return ok_response(
        [
            outcome.to_dict()
            for outcome in JsonlDecisionStore(workspace).list_outcomes(
                limit=limit, decision_id=decision_id
            )
        ]
    )


def handle_inspector_incomplete_decisions() -> dict[str, Any]:
    from nous_runtime.intelligence import lifecycle_for_workspace
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    if workspace is None:
        return ok_response([])
    return ok_response(
        [
            decision.to_dict()
            for decision in lifecycle_for_workspace(
                str(workspace)
            ).incomplete_decisions()
        ]
    )


def handle_inspector_provider_reliability(provider_id: str = "") -> dict[str, Any]:
    from nous_runtime.intelligence.reliability import JsonlReliabilityStore
    from nous_runtime.intelligence.profiles import JsonlProfileStore
    from nous_runtime.intelligence.replay import frozen_replay_summary
    from nous_runtime.intelligence import JsonlDecisionStore
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    if workspace is None:
        return ok_response([])
    store = JsonlReliabilityStore(workspace)
    profiles = JsonlProfileStore(workspace)
    if provider_id:
        health = store.get_current_health(provider_id, "")
        circuit = store.get_circuit_state(f"{provider_id}:*")
        observations = [
            item.to_dict()
            for item in profiles.list_performance_observations(limit=50)
            if item.provider_id == provider_id
        ]
        return ok_response(
            {
                "provider_id": provider_id,
                "health": health.to_dict() if health else None,
                "circuit": circuit.to_dict() if circuit else None,
                "recent_failures": [
                    item.to_dict()
                    for item in store.list_signals(provider_id=provider_id, limit=20)
                ],
                "recent_retries": [
                    item.to_dict()
                    for item in store.list_retries(provider_id=provider_id, limit=20)
                ],
                "fallback_chains": [
                    item.to_dict() for item in store.list_fallbacks(limit=20)
                ],
                "profile_observations": observations[-20:],
            }
        )
    decisions = JsonlDecisionStore(workspace).list_decisions(limit=20)
    return ok_response(
        {
            "integrity": store.verify_integrity(),
            "recent_failures": [
                item.to_dict() for item in store.list_signals(limit=20)
            ],
            "recent_retries": [item.to_dict() for item in store.list_retries(limit=20)],
            "fallback_chains": [
                item.to_dict() for item in store.list_fallbacks(limit=20)
            ],
            "profile_observation_count": len(
                profiles.list_performance_observations(limit=10000)
            ),
            "frozen_replay": [
                frozen_replay_summary(decision) for decision in decisions
            ],
            "deprecated_path_diagnostics": [
                {
                    "path": "nous_runtime.compat.provider.invoke_via_provider_observation",
                    "status": "compatibility_routed",
                    "canonical": "nous_runtime.intelligence.reliability.executor.execute_provider_observation",
                }
            ],
        }
    )


def handle_inspector_consistency() -> dict[str, Any]:
    from nous_runtime.intelligence.consistency import verify_cross_store_consistency
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    if workspace is None:
        return ok_response({"ok": True, "findings": [], "counts": {}})
    return ok_response(verify_cross_store_consistency(workspace))


# Context Runtime handlers (Phase 3)


def _get_context_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace

        return find_workspace() or ""
    except Exception:
        return ""


def handle_context_current() -> dict[str, Any]:
    """Build and return current context snapshot."""
    try:
        from nous_runtime.context.builder import BuildRequest, build_context

        ws = _get_context_workspace()
        request = BuildRequest(intent="api_request", max_items=100)
        snapshot = build_context(request, workspace=ws)
        return ok_response(snapshot.to_dict())
    except Exception as e:
        return err_response("CONTEXT_BUILD_ERROR", str(e))


def handle_context_history() -> dict[str, Any]:
    """List context snapshot history."""
    try:
        from nous_runtime.context.snapshot import list_snapshots

        ws = _get_context_workspace()
        snapshots = list_snapshots(workspace=ws, limit=50)
        return ok_response(snapshots)
    except Exception as e:
        return err_response("CONTEXT_HISTORY_ERROR", str(e))


def handle_context_explain() -> dict[str, Any]:
    """Explain the current context snapshot."""
    try:
        from nous_runtime.context.explain import explain_snapshot
        from nous_runtime.context.store import ContextStore

        ws = _get_context_workspace()
        store = ContextStore(ws)
        active = store.list(status="active", limit=1)
        if not active:
            return err_response(
                "CONTEXT_NOT_FOUND", "No active context snapshot found."
            )
        exp = explain_snapshot(active[0])
        return ok_response(exp.to_dict())
    except Exception as e:
        return err_response("CONTEXT_EXPLAIN_ERROR", str(e))


def handle_context_timeline() -> dict[str, Any]:
    """Show context timeline."""
    try:
        from nous_runtime.context.store import ContextStore

        ws = _get_context_workspace()
        store = ContextStore(ws)
        snapshots = store.list(limit=50, order="ASC")
        timeline = [
            {
                "id": s.id,
                "timestamp": s.timestamp,
                "status": s.status,
                "item_count": s.item_count,
                "confidence": s.confidence,
                "intent": s.metadata.get("intent", ""),
            }
            for s in snapshots
        ]
        return ok_response(timeline)
    except Exception as e:
        return err_response("CONTEXT_TIMELINE_ERROR", str(e))


def handle_context_snapshot(body: dict | None = None) -> dict[str, Any]:
    """Create a new context snapshot."""
    try:
        from nous_runtime.context.snapshot import create_snapshot

        ws = _get_context_workspace()
        intent = (body or {}).get("intent", "api_snapshot")
        snapshot = create_snapshot(workspace=ws, intent=intent)
        return ok_response(snapshot.to_dict())
    except Exception as e:
        return err_response("CONTEXT_SNAPSHOT_ERROR", str(e))


def handle_context_restore(body: dict | None = None) -> dict[str, Any]:
    """Restore context from a snapshot."""
    try:
        from nous_runtime.context.snapshot import restore_snapshot

        ws = _get_context_workspace()
        snapshot_id = (body or {}).get("snapshot_id", "")
        result = restore_snapshot(snapshot_id=snapshot_id, workspace=ws)
        return ok_response(result.to_dict())
    except Exception as e:
        return err_response("CONTEXT_RESTORE_ERROR", str(e))


# Evaluation Runtime handlers (Phase 4)


def _get_eval_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace

        return find_workspace() or ""
    except Exception:
        return ""


def handle_evaluation_current() -> dict[str, Any]:
    """Get the most recent evaluation record."""
    try:
        from nous_runtime.evaluation.history import EvaluationHistory

        ws = _get_eval_workspace()
        history = EvaluationHistory(ws)
        records = history.list(limit=1)
        if not records:
            return err_response("EVAL_NOT_FOUND", "No evaluation records found.")
        return ok_response(records[0].to_dict())
    except Exception as e:
        return err_response("EVAL_CURRENT_ERROR", str(e))


def handle_evaluation_history() -> dict[str, Any]:
    """List evaluation history."""
    try:
        from nous_runtime.evaluation.history import EvaluationHistory

        ws = _get_eval_workspace()
        history = EvaluationHistory(ws)
        records = history.list(limit=50)
        return ok_response([r.to_dict() for r in records])
    except Exception as e:
        return err_response("EVAL_HISTORY_ERROR", str(e))


def handle_evaluation_report() -> dict[str, Any]:
    """Get the current evaluation report."""
    try:
        from nous_runtime.evaluation.history import EvaluationHistory
        from nous_runtime.evaluation.report import generate_json_report

        ws = _get_eval_workspace()
        history = EvaluationHistory(ws)
        records = history.list(limit=1)
        if not records:
            return err_response("EVAL_NOT_FOUND", "No evaluation records found.")
        return ok_response(generate_json_report(records[0]))
    except Exception as e:
        return err_response("EVAL_REPORT_ERROR", str(e))


def handle_evaluation_run(body: dict | None = None) -> dict[str, Any]:
    """Run a new evaluation."""
    try:
        from nous_runtime.evaluation.evaluator import EvaluationEngine

        ws = _get_eval_workspace()
        body = body or {}
        target_type = body.get("target_type", "project")
        target_id = body.get("target_id", "current")
        engine = EvaluationEngine(workspace=ws)
        record = engine.evaluate(
            target_type=target_type,
            target_id=target_id,
            input_summary=body.get("input_summary", "API evaluation"),
        )
        return ok_response(record.to_dict())
    except Exception as e:
        return err_response("EVAL_RUN_ERROR", str(e))


# Experience Runtime handlers (Phase 5)


def _get_exp_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace

        return find_workspace() or ""
    except Exception:
        return ""


def handle_experience_list() -> dict[str, Any]:
    try:
        from nous_runtime.experience.store import ExperienceStore

        ws = _get_exp_workspace()
        store = ExperienceStore(ws)
        records = store.list(limit=50)
        return ok_response([r.to_dict() for r in records])
    except Exception as e:
        return err_response("EXP_LIST_ERROR", str(e))


def handle_experience_search() -> dict[str, Any]:
    try:
        from nous_runtime.experience.similarity import SimilarityEngine

        engine = SimilarityEngine()
        results = engine.find_similar_tasks("", limit=20)
        return ok_response([{"record": r.to_dict(), "score": s} for r, s in results])
    except Exception as e:
        return err_response("EXP_SEARCH_ERROR", str(e))


def handle_experience_recommend() -> dict[str, Any]:
    try:
        from nous_runtime.experience.recommendation import RecommendationEngine

        engine = RecommendationEngine()
        recs = engine.recommend("general task")
        return ok_response([r.to_dict() for r in recs])
    except Exception as e:
        return err_response("EXP_RECOMMEND_ERROR", str(e))


def handle_phase5_experience_stats() -> dict[str, Any]:
    try:
        from nous_runtime.experience.analyzer import ExperienceAnalyzer
        from nous_runtime.experience.store import ExperienceStore

        ws = _get_exp_workspace()
        analyzer = ExperienceAnalyzer(ExperienceStore(ws))
        return ok_response(analyzer.summary())
    except Exception as e:
        return err_response("EXP_STATS_ERROR", str(e))


# Phase 8 Runtime Closure handlers


def handle_runtime_run(
    body: dict,
    *,
    authorization_context=None,
    governance_surface: str = "local_cli",
) -> dict[str, Any]:
    try:
        from nous_runtime.runtime.orchestrator import RuntimeOrchestrator
        from nous_runtime.runtime.request import RuntimeRequest

        text = str(body.get("user_input") or body.get("text") or "")
        if not text.strip():
            return err_response("NOUS_INVALID_REQUEST", "user_input is required")
        response = RuntimeOrchestrator().run(
            RuntimeRequest(
                text,
                workspace=str(body.get("workspace") or ""),
                session=str(body.get("session") or ""),
                user_id=authorization_context.subject_id
                if authorization_context
                else "api",
                constraints=dict(body.get("constraints") or {}),
                authorization_context=authorization_context.to_dict()
                if authorization_context
                else {},
                governance_surface=governance_surface,
            )
        )
        return ok_response(response.to_dict())
    except Exception as e:
        return err_response("RUNTIME_RUN_ERROR", str(e))


def handle_runtime_sessions() -> dict[str, Any]:
    try:
        from nous_runtime.runtime.session import RuntimeSessionStore

        return ok_response(RuntimeSessionStore().list())
    except Exception as e:
        return err_response("RUNTIME_SESSION_ERROR", str(e))


def handle_runtime_dashboard() -> dict[str, Any]:
    try:
        from nous_runtime.control_center.snapshot import control_center_snapshot

        return ok_response(
            control_center_snapshot(os.environ.get("NOUS_WORKSPACE_ROOT", "."))
        )
    except Exception as exc:
        return err_response("RUNTIME_DASHBOARD_ERROR", str(exc))


def handle_runtime_runs(limit: int = 20) -> dict[str, Any]:
    """List canonical runs from the existing EventStream."""
    from nous_runtime.events import EventStream

    root = os.environ.get("NOUS_WORKSPACE_ROOT", ".")
    return ok_response(
        [
            item.to_dict()
            for item in EventStream(root).list_runs(limit=max(1, min(int(limit), 200)))
        ]
    )


def handle_run_events(
    run_id: str,
    after_sequence: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    """Replay canonical persisted events for one Runtime run."""
    from nous_runtime.events import EventStream

    stream = EventStream(os.environ.get("NOUS_WORKSPACE_ROOT", "."))
    if stream.get_run(run_id) is None:
        return err_response("NOUS_NOT_FOUND", f"Run not found: {run_id}")
    events = list(
        stream.iter_persisted_events(
            run_id,
            after_sequence=max(0, int(after_sequence)),
            limit=max(1, min(int(limit), 1000)),
        )
    )
    return ok_response(
        {
            "run_id": run_id,
            "events": [event.to_dict() for event in events],
            "next_after_sequence": events[-1].sequence
            if events
            else max(0, int(after_sequence)),
        }
    )


def handle_global_search(
    q: str = "",
    limit: int = 40,
    scope: str = "all",
) -> dict[str, Any]:
    """Search bounded Runtime metadata and workspace content."""
    query = str(q or "").strip()
    if len(query) < 2:
        return ok_response({"query": query, "results": [], "count": 0})
    maximum = max(1, min(int(limit), 100))
    wanted = str(scope or "all").casefold()
    root = Path(os.environ.get("NOUS_WORKSPACE_ROOT", ".")).resolve()
    needle = query.casefold()
    results: list[dict[str, Any]] = []

    def add(
        kind: str, item_id: str, title: str, detail: str = "", path: str = ""
    ) -> None:
        if len(results) >= maximum:
            return
        results.append(
            {
                "kind": kind,
                "id": item_id,
                "title": title[:200],
                "detail": detail[:500],
                "path": path,
            }
        )

    if wanted in {"all", "conversation", "conversations"}:
        try:
            from nous_runtime.conversation import ConversationStore

            store = ConversationStore(root)
            conversations = store.list(limit=200)
            for conversation in conversations:
                if needle in conversation.title.casefold():
                    add(
                        "conversation",
                        conversation.conversation_id,
                        conversation.title or "Conversation",
                        conversation.updated_at,
                    )
            for message in store.search_messages(query, limit=maximum):
                add(
                    "conversation",
                    message.conversation_id,
                    message.content[:120].replace("\n", " "),
                    f"{message.role} · {message.created_at}",
                )
        except (OSError, ValueError):
            pass

    if len(results) < maximum and wanted in {"all", "artifact", "artifacts"}:
        try:
            from nous_runtime.artifact import registry as artifact_registry

            for artifact in artifact_registry.list():
                searchable = " ".join(
                    (
                        str(getattr(artifact, "name", "")),
                        str(getattr(artifact, "location", "")),
                        str(getattr(artifact, "type", "")),
                    )
                )
                if needle in searchable.casefold():
                    add(
                        "artifact",
                        str(getattr(artifact, "id", "")),
                        str(getattr(artifact, "name", "Artifact")),
                        str(getattr(artifact, "type", "")),
                        str(getattr(artifact, "location", "")),
                    )
        except (OSError, ValueError):
            pass

    if len(results) < maximum and wanted in {"all", "run", "runs", "trace", "traces"}:
        try:
            from nous_runtime.events import EventStream

            for run in EventStream(root).list_runs(limit=200):
                searchable = " ".join((run.run_id, run.task_id, str(run.metadata)))
                if needle in searchable.casefold():
                    add("run", run.run_id, run.task_id or run.run_id, run.state.value)
        except (OSError, ValueError):
            pass

    if len(results) < maximum and wanted in {"all", "file", "files", "workspace"}:
        scanned = 0
        excluded = {".git", ".nous", "node_modules", "target", "__pycache__", ".venv"}
        try:
            for path in root.rglob("*"):
                if len(results) >= maximum or scanned >= 2_000:
                    break
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                if any(part in excluded for part in relative.parts):
                    continue
                scanned += 1
                matched = needle in relative.as_posix().casefold()
                snippet = ""
                if not matched and path.stat().st_size <= 262_144:
                    try:
                        text_content = path.read_text(encoding="utf-8")
                        position = text_content.casefold().find(needle)
                        if position >= 0:
                            matched = True
                            snippet = text_content[
                                max(0, position - 60) : position + 180
                            ].replace("\n", " ")
                    except (OSError, UnicodeError):
                        pass
                if matched:
                    add(
                        "file",
                        relative.as_posix(),
                        path.name,
                        snippet or relative.as_posix(),
                        relative.as_posix(),
                    )
        except OSError:
            pass
    return ok_response(
        {"query": query, "scope": wanted, "results": results, "count": len(results)}
    )


def handle_workspace() -> dict[str, Any]:
    """Describe the active workspace through the existing Workspace Registry."""
    from nous_runtime.workspace.registry import WorkspaceRegistry

    registry = WorkspaceRegistry(os.environ.get("NOUS_WORKSPACE_ROOT", "."))
    active = registry.active()
    return ok_response(
        {
            "active": active.to_dict() if active else None,
            "workspaces": [item.to_dict() for item in registry.list()],
        }
    )


def handle_approvals() -> dict[str, Any]:
    """List pending approvals from the authoritative ApprovalBroker."""
    from nous_runtime.governance.broker import get_broker

    return ok_response({"approvals": get_broker().get_pending()})


def handle_workflow_run(body: dict[str, Any]) -> dict[str, Any]:
    """Start a registered workflow through the existing Workflow Runtime."""
    try:
        from nous_runtime.workflow import WorkflowRuntime

        runtime = WorkflowRuntime(os.environ.get("NOUS_WORKSPACE_ROOT", "."))
        run = runtime.start(
            str(body.get("workflow_id") or ""),
            str(body.get("version") or "1.0.0"),
            dict(body.get("inputs") or {}),
            idempotency_key=str(body.get("idempotency_key") or ""),
        )
        return ok_response(
            {
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "state": run.state.value,
                "step_states": dict(run.step_states),
                "outputs": dict(run.outputs),
                "error": run.error,
            }
        )
    except (KeyError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def _model_center_service():
    from nous_runtime.model_runtime.center import ModelCenterService

    return ModelCenterService(os.environ.get("NOUS_WORKSPACE_ROOT", ".nous"))


def handle_model_center() -> dict[str, Any]:
    try:
        return ok_response(_model_center_service().snapshot())
    except Exception as exc:
        return err_response("MODEL_CENTER_ERROR", str(exc))


def handle_model_center_action(body: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(body.get("action") or "").strip().lower()
        model_id = str(body.get("model_id") or "").strip()
        if not action or not model_id:
            return err_response(
                "NOUS_INVALID_REQUEST",
                "action and model_id are required",
            )
        center = _model_center_service()
        if action in {"enable", "disable", "remove", "repair", "verify"}:
            return ok_response(getattr(center, action)(model_id))
        if action in {"install", "update"}:
            from pathlib import Path

            workspace = Path(os.environ.get("NOUS_WORKSPACE_ROOT", ".nous")).resolve()
            catalog = Path(str(body.get("catalog_path") or "")).resolve()
            allowed = (workspace / "models" / "catalogs").resolve()
            if not catalog.is_relative_to(allowed):
                return err_response(
                    "NOUS_INVALID_REQUEST",
                    "catalog_path must be inside workspace/models/catalogs",
                )
            result = getattr(center, action)(
                catalog,
                model_id,
                public_key=os.environ.get("NOUS_MODEL_CATALOG_PUBLIC_KEY", ""),
                allow_unsigned=(
                    os.environ.get("NOUS_ALLOW_UNSIGNED_LOCAL_CATALOG", "0") == "1"
                ),
                accept_license=bool(body.get("accept_license", False)),
            )
            return ok_response(result)
        return err_response(
            "NOUS_INVALID_REQUEST",
            f"unsupported model action: {action}",
        )
    except Exception as exc:
        return err_response("MODEL_CENTER_ACTION_ERROR", str(exc))


def handle_model_select(body: dict) -> dict[str, Any]:
    try:
        from nous_runtime.model.runtime import ModelRuntime
        from nous_runtime.model.types import ModelRequest

        task_type = str(body.get("task_type") or "general")
        request = ModelRequest(
            task_type=task_type,
            context=str(body.get("context") or ""),
            privacy=str(body.get("privacy") or "standard"),
            cost=float(body.get("cost") or 0.0),
            latency=int(body.get("latency") or 0),
            quality=float(body.get("quality") or 0.0),
            metadata=dict(body.get("metadata") or {}),
        )
        return ok_response(ModelRuntime().select(request).to_dict())
    except Exception as e:
        return err_response("MODEL_SELECT_ERROR", str(e))


def handle_chat_runtime(
    body: dict[str, Any],
    *,
    authorization_context=None,
    governance_surface: str = "local_cli",
) -> dict[str, Any]:
    try:
        from nous_runtime.chat import ChatRequest, ChatRuntime

        subject_id = getattr(authorization_context, "subject_id", "") or "local"
        response = ChatRuntime(os.environ.get("NOUS_WORKSPACE_ROOT", ".")).send(
            ChatRequest(
                text=str(body.get("text") or ""),
                workspace_id=str(body.get("workspace_id") or "default"),
                owner_id=subject_id,
                conversation_id=str(body.get("conversation_id") or ""),
                attachment_ids=tuple(
                    str(item) for item in body.get("attachment_ids") or ()
                ),
                model_id=str(body.get("model_id") or ""),
                agent_mode=str(body.get("agent_mode") or "agent"),
                request_id=str(body.get("request_id") or ""),
            ),
            authorization_context=authorization_context.to_dict()
            if authorization_context
            else {},
            governance_surface=governance_surface,
        )
        return ok_response(
            {
                "conversation_id": response.conversation_id,
                "intent": response.intent.value,
                "status": response.status,
                "message": response.message,
                "trace_id": response.trace_id,
                "run_id": str(response.data.get("run_id") or ""),
                "task_promoted": response.task_promoted,
                "requires_trusted_approval": response.requires_trusted_approval,
                "data": response.data,
            }
        )
    except (PermissionError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))
    except Exception as exc:
        return err_response("NOUS_CHAT_ERROR", str(exc))


def handle_ide_runtime(
    body: dict[str, Any],
    *,
    authorization_context=None,
    governance_surface: str = "server",
) -> dict[str, Any]:
    """Dispatch editor-neutral IDE requests without creating IDE-owned state."""
    del governance_surface
    from nous_runtime.ide import IDERequest, IDERuntimeProtocol

    response = IDERuntimeProtocol(os.environ.get("NOUS_WORKSPACE_ROOT", ".")).handle(
        IDERequest(
            action=str(body.get("action") or ""),
            params=dict(body.get("params") or {}),
            subject_id=getattr(authorization_context, "subject_id", "") or "",
        )
    )
    if response.ok:
        return ok_response(response.data)
    return err_response("NOUS_IDE_REQUEST_ERROR", response.error)


# Route Table

ROUTES = {
    ("GET", "/api/v1/status"): handle_status,
    ("GET", "/api/v1/health"): handle_health,
    ("GET", "/api/v1/version"): handle_version,
    ("GET", "/api/v1/usage"): handle_usage_summary,
    ("GET", "/api/v1/capabilities"): handle_list_capabilities,
    ("POST", "/api/v1/capabilities/run"): handle_run_capability,
    ("GET", "/api/v1/providers"): handle_list_providers,
    ("GET", "/api/v1/providers/health"): handle_provider_health,
    ("GET", "/api/v1/packs"): handle_list_packs,
    ("POST", "/api/v1/packs/install"): handle_install_pack,
    ("DELETE", "/api/v1/packs/{name}"): handle_remove_pack,
    ("GET", "/api/v1/jobs"): handle_list_jobs,
    ("GET", "/api/v1/jobs/{job_id}"): handle_get_job,
    ("GET", "/api/v1/traces"): handle_list_traces,
    # Nodes API (v1)
    ("GET", "/api/v1/nodes"): handle_list_nodes,
    ("GET", "/api/v1/nodes/{node_id}"): handle_get_node,
    ("POST", "/api/v1/nodes/scan"): handle_scan_nodes,
    # Artifacts API (v1)
    ("GET", "/api/v1/artifacts"): handle_list_artifacts,
    ("GET", "/api/v1/artifacts/{artifact_id}"): handle_get_artifact,
    # Approvals API (v1)
    ("POST", "/api/v1/approvals/{request_id}/{action}"): handle_approval_action,
    # Events API (v1) — SSE streaming
    ("GET", "/api/v1/events/stream"): handle_events_stream,
    # Model observations API
    ("GET", "/api/v1/models/observations"): handle_model_observations,
    ("GET", "/api/v1/models/rankings"): handle_model_rankings,
    # Execution traces API
    ("GET", "/api/v1/traces/{trace_id}"): handle_get_trace,
    ("GET", "/api/v1/traces/{trace_id}/timeline"): handle_trace_timeline,
    ("POST", "/api/v1/runtime/run"): handle_runtime_run,
    ("POST", "/api/v1/chat"): handle_chat_runtime,
    ("POST", "/api/v1/ide/runtime"): handle_ide_runtime,
    ("GET", "/api/v1/runtime/sessions"): handle_runtime_sessions,
    ("GET", "/api/v1/runtime/dashboard"): handle_runtime_dashboard,
    ("GET", "/api/v1/runtime/runs"): handle_runtime_runs,
    ("GET", "/api/v1/runtime/runs/{run_id}/events"): handle_run_events,
    ("GET", "/api/v1/search"): handle_global_search,
    ("GET", "/api/v1/workspace"): handle_workspace,
    ("GET", "/api/v1/control/approvals"): handle_approvals,
    ("POST", "/api/v1/workflow/run"): handle_workflow_run,
    ("POST", "/api/v1/model/select"): handle_model_select,
    ("GET", "/api/v1/models"): handle_model_center,
    ("POST", "/api/v1/models/action"): handle_model_center_action,
    ("GET", "/api/v1/inspector/runtime"): handle_inspector_runtime,
    ("GET", "/api/v1/inspector/capabilities"): handle_inspector_capabilities,
    ("GET", "/api/v1/inspector/tasks"): handle_inspector_tasks,
    ("GET", "/api/v1/inspector/observations"): handle_inspector_observations,
    ("GET", "/api/v1/inspector/memory"): handle_inspector_memory,
    ("GET", "/api/v1/inspector/decisions"): handle_inspector_decisions,
    (
        "GET",
        "/api/v1/inspector/decision/candidates",
    ): handle_inspector_decision_candidates,
    ("GET", "/api/v1/inspector/decision/ranking"): handle_inspector_decision_ranking,
    (
        "GET",
        "/api/v1/inspector/decision/constraints",
    ): handle_inspector_decision_constraints,
    ("GET", "/api/v1/inspector/decision/score"): handle_inspector_decision_score,
    ("GET", "/api/v1/inspector/outcomes"): handle_inspector_outcomes,
    (
        "GET",
        "/api/v1/inspector/decisions/incomplete",
    ): handle_inspector_incomplete_decisions,
    (
        "GET",
        "/api/v1/inspector/providers/reliability",
    ): handle_inspector_provider_reliability,
    ("GET", "/api/v1/inspector/consistency"): handle_inspector_consistency,
    ("GET", "/api/v1/inspector/diagnostics"): handle_inspector_diagnostics,
    ("GET", "/api/v1/inspector/checkpoints"): handle_inspector_checkpoints,
    (
        "POST",
        "/api/v1/inspector/checkpoints/retention",
    ): handle_inspector_checkpoint_retention,
    # Context Runtime (Phase 3)
    ("GET", "/api/v1/context/current"): handle_context_current,
    ("GET", "/api/v1/context/history"): handle_context_history,
    ("GET", "/api/v1/context/explain"): handle_context_explain,
    ("GET", "/api/v1/context/timeline"): handle_context_timeline,
    ("POST", "/api/v1/context/snapshot"): handle_context_snapshot,
    ("POST", "/api/v1/context/restore"): handle_context_restore,
    # Evaluation Runtime (Phase 4)
    ("GET", "/api/v1/evaluation/current"): handle_evaluation_current,
    ("GET", "/api/v1/evaluation/history"): handle_evaluation_history,
    ("GET", "/api/v1/evaluation/report"): handle_evaluation_report,
    ("POST", "/api/v1/evaluation/run"): handle_evaluation_run,
    # Experience Runtime (Phase 5)
    ("GET", "/api/v1/experience/list"): handle_experience_list,
    ("GET", "/api/v1/experience/search"): handle_experience_search,
    ("GET", "/api/v1/experience/recommend"): handle_experience_recommend,
    ("GET", "/api/v1/experience/stats"): handle_phase5_experience_stats,
    # Enhanced health/status endpoints for desktop bootstrap
    ("GET", "/api/v1/health/detailed"): None,  # placeholder, replaced below
    ("GET", "/live"): None,
    ("GET", "/ready"): None,
    ("GET", "/api/v1/runtime/status"): None,
    ("GET", "/api/v1/workspace/status"): None,
    ("GET", "/api/v1/provider/status"): None,
    ("POST", "/api/v1/session/refresh"): None,
}

# Register enhanced health endpoints
try:
    from nous_runtime.api.health_endpoints import (
        handle_health_detailed,
        handle_live,
        handle_ready,
        handle_runtime_status,
        handle_workspace_status,
        handle_provider_status,
        handle_session_refresh,
    )

    ROUTES[("GET", "/api/v1/health/detailed")] = handle_health_detailed
    ROUTES[("GET", "/live")] = handle_live
    ROUTES[("GET", "/ready")] = handle_ready
    ROUTES[("GET", "/api/v1/runtime/status")] = handle_runtime_status
    ROUTES[("GET", "/api/v1/workspace/status")] = handle_workspace_status
    ROUTES[("GET", "/api/v1/provider/status")] = handle_provider_status
    ROUTES[("POST", "/api/v1/session/refresh")] = handle_session_refresh
except ImportError:
    pass

# Desktop UI routes — thin adapters over Runtime primitives
try:
    from nous_runtime.api.desktop_routes import DESKTOP_ROUTES

    ROUTES.update(DESKTOP_ROUTES)
except ImportError:
    pass

# Task Center routes — timeline, graph, artifacts, verification
try:
    from nous_runtime.api.task_center_routes import TASK_CENTER_ROUTES

    ROUTES.update(TASK_CENTER_ROUTES)
except ImportError:
    pass

# Developer Platform routes - projects, runs, experiments, and Model Lab
try:
    from nous_runtime.api.developer_routes import DEVELOPER_ROUTES

    ROUTES.update(DEVELOPER_ROUTES)
except ImportError:
    pass

# Research routes - governed network, Source, Snapshot, and Evidence
try:
    from nous_runtime.api.research_routes import RESEARCH_ROUTES

    ROUTES.update(RESEARCH_ROUTES)
except ImportError:
    pass

# Document Workbench routes - governed Document IR and verified DOCX/PDF artifacts
try:
    from nous_runtime.api.document_routes import DOCUMENT_ROUTES

    ROUTES.update(DOCUMENT_ROUTES)
except ImportError:
    pass

# Environment Inspector routes - governed execution environments and providers
try:
    from nous_runtime.api.environment_routes import ENVIRONMENT_ROUTES

    ROUTES.update(ENVIRONMENT_ROUTES)
except ImportError:
    pass
# Simulation Workbench routes - reproducible scientific execution and replay
try:
    from nous_runtime.api.simulation_routes import SIMULATION_ROUTES

    ROUTES.update(SIMULATION_ROUTES)
except ImportError:
    pass

# Scientific Runtime routes - qualified providers, claims, and reports
try:
    from nous_runtime.api.scientific_routes import SCIENTIFIC_ROUTES

    ROUTES.update(SCIENTIFIC_ROUTES)
except ImportError:
    pass

# Health Dashboard routes
try:
    from nous_runtime.api.health_dashboard import HEALTH_DASHBOARD_ROUTES

    ROUTES.update(HEALTH_DASHBOARD_ROUTES)
except ImportError:
    pass

# Control Plane routes — unified v1 API for desktop
try:
    from nous_runtime.control_plane.routes import CONTROL_PLANE_ROUTES

    ROUTES.update(CONTROL_PLANE_ROUTES)
except ImportError:
    pass

# v2 Intelligence & Discovery API — /api/v2/* routes
try:
    from nous_runtime.api.v2_routes import V2_ROUTES

    ROUTES.update(V2_ROUTES)
except ImportError:
    pass


# Backward-compatible aliases for pre-versioned clients. Handlers remain
# authoritative under /api/v1; aliases are references, not duplicate logic.
LEGACY_ROUTE_ALIASES: dict[tuple[str, str], tuple[str, str]] = {}
for canonical_key in tuple(ROUTES):
    canonical_method, canonical_path = canonical_key
    if canonical_path.startswith("/api/v1/"):
        legacy_key = (canonical_method, canonical_path.replace("/api/v1/", "/api/", 1))
        ROUTES.setdefault(legacy_key, ROUTES[canonical_key])
        LEGACY_ROUTE_ALIASES[legacy_key] = canonical_key

GOVERNED_MUTATION_ROUTES = {
    ("POST", "/api/v1/packs/install"): (
        "pack.install",
        "external_write",
        "partially_reversible",
    ),
    ("DELETE", "/api/v1/packs/{name}"): (
        "pack.remove",
        "destructive",
        "partially_reversible",
    ),
    ("POST", "/api/v1/context/snapshot"): (
        "context.snapshot",
        "local_write",
        "reversible",
    ),
    ("POST", "/api/v1/inspector/checkpoints/retention"): (
        "checkpoint.retention",
        "destructive",
        "irreversible",
    ),
    ("POST", "/api/v1/context/restore"): (
        "context.restore",
        "local_write",
        "reversible",
    ),
    ("POST", "/api/v1/evaluation/run"): ("evaluation.run", "local_write", "reversible"),
    ("POST", "/api/v1/workflow/run"): (
        "workflow.run",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/models/action"): (
        "model.manage",
        "external_write",
        "partially_reversible",
    ),
}

try:
    from nous_runtime.api.desktop_routes import DESKTOP_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(DESKTOP_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.api.developer_routes import DEVELOPER_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(DEVELOPER_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.api.research_routes import RESEARCH_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(RESEARCH_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.api.document_routes import DOCUMENT_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(DOCUMENT_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.api.environment_routes import ENVIRONMENT_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(ENVIRONMENT_GOVERNANCE)
except ImportError:
    pass
try:
    from nous_runtime.api.simulation_routes import SIMULATION_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(SIMULATION_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.control_plane.routes import CONTROL_PLANE_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(CONTROL_PLANE_GOVERNANCE)
except ImportError:
    pass

try:
    from nous_runtime.api.scientific_routes import SCIENTIFIC_GOVERNANCE

    GOVERNED_MUTATION_ROUTES.update(SCIENTIFIC_GOVERNANCE)
except ImportError:
    pass

# Legacy mutation routes receive the same governance policy as their v1 target.
for legacy_key, canonical_key in LEGACY_ROUTE_ALIASES.items():
    governance = GOVERNED_MUTATION_ROUTES.get(canonical_key)
    if governance is not None:
        GOVERNED_MUTATION_ROUTES.setdefault(legacy_key, governance)

_PATH_PARAMETER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _match_route(method: str, path: str):
    exact = ROUTES.get((method, path))
    if exact is not None:
        return exact, path, {}
    actual_parts = path.strip("/").split("/")
    for (route_method, pattern), handler in ROUTES.items():
        if route_method != method or "{" not in pattern:
            continue
        pattern_parts = pattern.strip("/").split("/")
        if len(actual_parts) != len(pattern_parts):
            continue
        captured: dict[str, str] = {}
        matched = True
        for expected, actual in zip(pattern_parts, actual_parts):
            if expected.startswith("{") and expected.endswith("}"):
                value = unquote(actual)
                if not _PATH_PARAMETER.fullmatch(value):
                    matched = False
                    break
                captured[expected[1:-1]] = value
            elif expected != actual:
                matched = False
                break
        if matched:
            return handler, pattern, captured
    return None, "", {}


def _authorize_mutation_route(
    method: str,
    route_path: str,
    body: dict | None,
    params: dict[str, Any],
    authorization_context,
    *,
    surface: str,
) -> dict[str, Any] | None:
    governance = GOVERNED_MUTATION_ROUTES.get((method, route_path))
    if governance is None:
        return None
    if authorization_context is None:
        return err_response("NOUS_UNAUTHENTICATED", "Authentication required")
    capability_id, side_effect_class, reversibility = governance
    if (
        capability_id == "project.control"
        and str((body or {}).get("action") or "").lower() == "cancel"
    ):
        capability_id = "project.cancel"
        side_effect_class = "destructive"
        reversibility = "partially_reversible"
    try:
        from nous_runtime.governance import ActionProposal, get_gate
        from nous_runtime.governance.runtime_mode import should_fail_closed

        proposal_params = {"body": dict(body or {}), "path_params": dict(params)}
        affected_resources = tuple(str(value) for value in params.values())
        external_recipients: tuple[str, ...] = ()
        required_permissions: tuple[str, ...] = ()
        data_classification = "internal"
        retry_behavior = "unknown"
        if capability_id == "network.fetch":
            from nous_runtime.evidence.service import (
                safe_request_summary,
                search_network_values,
            )

            network_values = dict(body or {})
            if route_path == "/api/v1/research/search":
                network_values = search_network_values(network_values)
            network_summary = safe_request_summary(network_values)
            proposal_params = {"body": network_summary, "path_params": dict(params)}
            safe_url = str(network_summary.get("url") or "")
            host = (urlsplit(safe_url).hostname or "").lower()
            affected_resources = (safe_url,)
            external_recipients = (host,) if host else ()
            required_permissions = ("network",)
            data_classification = (
                "confidential"
                if any(
                    network_values.get(key)
                    for key in ("credential_ref", "body", "json", "body_ref")
                )
                else "internal"
            )
            retry_behavior = (
                "idempotent"
                if str(network_values.get("method") or "GET").upper() in {"GET", "HEAD"}
                else "unsafe"
            )
        if capability_id.startswith("environment."):
            environment_values = dict(body or {})
            environment_permissions = set()
            network_policy = environment_values.get("network_policy") or {}
            if (
                isinstance(network_policy, dict)
                and str(network_policy.get("mode") or "none") != "none"
            ):
                environment_permissions.add("network.http")
                external_recipients = tuple(
                    str(host).lower()
                    for host in (network_policy.get("allowed_hosts") or [])
                )
            for mount in environment_values.get("workspace_mounts") or []:
                if not isinstance(mount, dict):
                    continue
                mode = str(mount.get("mode") or "read-only")
                environment_permissions.add(
                    "workspace.read" if mode == "read-only" else "workspace.write"
                )
            device_policy = environment_values.get("device_policy") or {}
            if isinstance(device_policy, dict):
                if (
                    str(
                        device_policy.get("gpu")
                        or environment_values.get("gpu_policy")
                        or "none"
                    )
                    != "none"
                ):
                    environment_permissions.add("gpu.compute")
                if device_policy.get("devices"):
                    environment_permissions.add("device.access")
            environment_permissions.add("runtime.execute")
            required_permissions = tuple(sorted(environment_permissions))
            retry_behavior = "unsafe"
        if capability_id.startswith("simulation."):
            required_permissions = ("runtime.execute", "simulation.compute")
            retry_behavior = "unsafe"

        if capability_id.startswith("scientific."):
            required_permissions = ("runtime.execute", "scientific.compute")
            retry_behavior = "unsafe"

        proposal = ActionProposal(
            action_type="api.mutation",
            capability_id=capability_id,
            params=proposal_params,
            parameter_summary=f"{method} {route_path}",
            target_workspace=str((body or {}).get("workspace") or ""),
            affected_resources=affected_resources,
            data_classification=data_classification,
            external_recipients=external_recipients,
            side_effect_class=side_effect_class,
            retry_behavior=retry_behavior,
            required_permissions=required_permissions,
            reversibility=reversibility,
            deployment_channel="api",
            locality=authorization_context.session_locality,
            # API retries must reproduce the same proposal hash so a one-use
            # approval lease can authorize exactly the reviewed request.
            created_at="",
        )
        decision = get_gate().evaluate(proposal, authorization_context)
        if decision.action_mode == "EXECUTE":
            if capability_id == "network.fetch":
                from nous_runtime.evidence.service import (
                    record_network_governance_event,
                )

                record_network_governance_event(
                    network_values,
                    "network.approved",
                    decision_id=decision.decision_id,
                    proposal_hash=proposal.proposal_hash,
                )
            return None
        if (
            not should_fail_closed(surface=surface)
            and decision.rule_class != "NON_OVERRIDABLE"
        ):
            log.warning(
                "Compatibility API mutation after governance decision: %s",
                decision.reason_code,
            )
            return None
        code = (
            "NOUS_APPROVAL_REQUIRED"
            if decision.action_mode == "ASK_APPROVAL"
            else "NOUS_UNAUTHORIZED"
        )
        details = {
            "decision_id": decision.decision_id,
            "action_mode": decision.action_mode,
        }
        if (
            decision.action_mode == "ASK_APPROVAL"
            and getattr(decision, "proposal_hash", "") == proposal.proposal_hash
        ):
            from nous_runtime.governance.broker import get_broker

            broker = get_broker()
            pending = next(
                (
                    item
                    for item in broker.get_pending()
                    if item.get("proposal_hash") == proposal.proposal_hash
                    and item.get("requested_by") == authorization_context.subject_id
                ),
                None,
            )
            if pending is None:
                request = broker.request_approval(
                    run_id=f"api-{decision.decision_id}",
                    task_id=f"{method} {route_path}",
                    proposal=proposal,
                    context=authorization_context,
                    requester=authorization_context.subject_id,
                    ttl_hours=1,
                )
                details["approval_request_id"] = request.request_id
            else:
                details["approval_request_id"] = pending.get("request_id", "")
        if capability_id == "network.fetch" and decision.action_mode == "ASK_APPROVAL":
            from nous_runtime.evidence.service import record_network_governance_event

            details["run_id"] = record_network_governance_event(
                dict(body or {}),
                "network.approval_required",
                approval_request_id=str(details.get("approval_request_id") or ""),
                decision_id=decision.decision_id,
                proposal_hash=proposal.proposal_hash,
            )
        return err_response(
            code,
            decision.reason_message or decision.reason_code,
            details,
        )
    except Exception as exc:
        from nous_runtime.governance.runtime_mode import should_fail_closed

        if should_fail_closed(surface=surface):
            log.exception("API governance evaluation failed: %s %s", method, route_path)
            return err_response(
                "NOUS_GOVERNANCE_UNAVAILABLE", "Governance evaluation unavailable"
            )
        log.warning("Compatibility API mutation without Gate: %s", exc)
        return None


def route(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
    auth: dict[str, Any] | None = None,
    surface: str = "local_cli",
) -> dict[str, Any]:
    """Route an API request to the appropriate handler."""
    method_upper = method.upper()

    # v1 API prefix normalization (RC1 freeze)
    # All routes are defined under /api/v1/. Requests to bare /api/
    # paths are transparently rewritten to /api/v1/ for backward
    # compatibility. This shim will be removed in v1.1.0.
    deprecation_notice = False
    if path.startswith("/api/") and not path.startswith(("/api/v1/", "/api/v2/")):
        path = path.replace("/api/", "/api/v1/", 1)
        deprecation_notice = True

    handler, route_path, path_params = _match_route(method_upper, path)
    if not handler:
        return err_response("NOUS_INVALID_REQUEST", f"No route: {method} {path}")

    auth_error = _authorize_api_request(method_upper, path, auth, surface=surface)
    if auth_error:
        return auth_error

    try:
        authorization_context = _authentication_context(auth, surface=surface)
        request_params = dict(path_params)
        for name, value in (params or {}).items():
            if name in request_params and request_params[name] != value:
                return err_response(
                    "NOUS_INVALID_REQUEST", f"Conflicting route parameter: {name}"
                )
            request_params[name] = value
        governance_error = _authorize_mutation_route(
            method_upper,
            route_path,
            body,
            request_params,
            authorization_context,
            surface=surface,
        )
        if governance_error:
            return governance_error
        if body is not None and handler in {
            handle_run_capability,
            handle_runtime_run,
            handle_chat_runtime,
            handle_ide_runtime,
        }:
            result = handler(
                body,
                authorization_context=authorization_context,
                governance_surface=surface,
            )
        elif body is not None:
            parameters = inspect.signature(handler).parameters
            accepted = {
                name: value
                for name, value in request_params.items()
                if name in parameters
            }
            if "body" in parameters:
                result = handler(**accepted, body=body)
            elif accepted:
                result = handler(**accepted)
            else:
                result = handler(body)
        elif request_params:
            parameters = inspect.signature(handler).parameters
            if set(parameters) == {"params"}:
                result = handler(request_params)
            else:
                result = handler(**request_params)
        else:
            parameters = inspect.signature(handler).parameters
            if set(parameters) == {"params"}:
                result = handler({})
            else:
                result = handler()

        # Inject deprecation notice for legacy /api/ paths
        if deprecation_notice and isinstance(result, dict):
            result.setdefault("meta", {})
            result["meta"]["deprecated_api_path"] = True
            result["meta"]["deprecation_message"] = (
                "Bare /api/ paths are deprecated. Use /api/v1/ instead. "
                "This compatibility shim will be removed in v1.1.0."
            )
        return result

    except Exception as e:
        log.exception("API route error: %s %s", method, path)
        return err_response("NOUS_INTERNAL_ERROR", str(e))


def route_server(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
    auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a request through the fail-closed server API surface."""
    return route(method, path, body=body, params=params, auth=auth, surface="server")
