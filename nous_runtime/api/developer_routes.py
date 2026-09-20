"""Developer Platform API over authoritative Runtime services."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _workspace() -> Path:
    return Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()


def _project_view(project: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.connectivity.project.coordinator import ProjectCoordinator

    progress = ProjectCoordinator().get_progress(str(project.get("project_id") or ""))
    return {**project, "progress": progress.to_dict() if progress is not None else None}


def handle_developer_overview() -> dict[str, Any]:
    from nous_runtime.connectivity.project.store import ProjectStore
    from nous_runtime.events import EventStream
    from nous_runtime.experiments import ExperimentService
    from nous_runtime.model_runtime.center import ModelCenterService

    root = _workspace()
    projects = ProjectStore().list_projects()
    runs = EventStream(str(root)).list_runs(limit=200)
    experiments = ExperimentService(root).snapshot()
    models = ModelCenterService(root).snapshot()
    return ok_response({
        "workspace": str(root),
        "projects": {"total": len(projects), "active": sum(item.get("status") == "active" for item in projects)},
        "runs": {"total": len(runs), "active": sum(item.state.value in {"RUNNING", "PLANNING", "RECOVERING"} for item in runs)},
        "experiments": experiments["summary"],
        "models": models["summary"],
    })


def handle_developer_projects(params: dict[str, Any] | None = None) -> dict[str, Any]:
    from nous_runtime.connectivity.project.store import ProjectStore

    state = str((params or {}).get("state") or "").strip().lower()
    projects = ProjectStore().list_projects()
    if state:
        projects = [item for item in projects if str(item.get("status") or "").lower() == state]
    return ok_response({"projects": [_project_view(item) for item in projects], "total": len(projects)})


def handle_developer_project(project_id: str) -> dict[str, Any]:
    from nous_runtime.connectivity.project.store import ProjectStore

    store = ProjectStore()
    project = store.get_project(project_id)
    if project is None:
        return err_response("NOUS_NOT_FOUND", f"Project not found: {project_id}")
    return ok_response({
        **_project_view(project),
        "plan": store.get_plan(project_id),
        "work_items": store.list_work_items(project_id),
        "checkpoints": store.list_checkpoints(project_id),
        "events": store.list_events(project_id),
    })


def handle_developer_project_create(body: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.connectivity.project.coordinator import ProjectCoordinator

    name = str(body.get("name") or "").strip()
    if not name:
        return err_response("NOUS_INVALID_REQUEST", "Project name is required")
    result = ProjectCoordinator().create_project(
        name,
        str(body.get("description") or "").strip(),
        str(body.get("owner") or "local").strip(),
    )
    if result is None:
        return err_response("PROJECT_CREATE_ERROR", "Project could not be created")
    return ok_response(result)


def handle_developer_project_action(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.connectivity.project.coordinator import ProjectCoordinator
    from nous_runtime.connectivity.project.store import ProjectStore

    action = str(body.get("action") or "").strip().lower()
    coordinator = ProjectCoordinator()
    if ProjectStore().get_project(project_id) is None:
        return err_response("NOUS_NOT_FOUND", f"Project not found: {project_id}")
    if action == "start":
        changed: Any = coordinator.activate(project_id)
    elif action == "pause":
        changed = coordinator.pause(project_id, str(body.get("reason") or "Desktop request"))
    elif action == "resume":
        changed = coordinator.resume(project_id)
    elif action == "cancel":
        changed = coordinator.cancel_project(project_id)
    elif action == "continue":
        decision = coordinator.continue_project(project_id)
        return ok_response({"project_id": project_id, "action": action, "decision": decision.to_dict()})
    else:
        return err_response("NOUS_INVALID_REQUEST", "action must be start, pause, resume, continue, or cancel")
    if not changed:
        return err_response("PROJECT_STATE_ERROR", f"Cannot {action} project in its current state")
    project = ProjectStore().get_project(project_id)
    return ok_response(_project_view(project or {"project_id": project_id}))


def handle_developer_runs(params: dict[str, Any] | None = None) -> dict[str, Any]:
    from nous_runtime.events import EventStream

    values = params or {}
    limit = max(1, min(int(values.get("limit", 50)), 200))
    state = str(values.get("state") or "").strip().upper()
    runs = EventStream(str(_workspace())).list_runs(limit=limit)
    if state:
        runs = [item for item in runs if item.state.value == state]
    records = [item.to_dict() for item in runs]
    for record in records:
        total = int(record.get("total_steps") or 0)
        completed = int(record.get("completed_steps") or 0)
        record["progress_pct"] = round((completed / total) * 100, 1) if total else 0.0
    return ok_response({"runs": records, "total": len(records)})


def handle_developer_experiments() -> dict[str, Any]:
    from nous_runtime.experiments import ExperimentService

    return ok_response(ExperimentService(_workspace()).snapshot())


def handle_developer_experiment_create(body: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.experiments import ExperimentService

    try:
        return ok_response(ExperimentService(_workspace()).create(body).to_dict())
    except (TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_developer_experiment_evaluate(experiment_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from nous_runtime.experiments import ExperimentService

    try:
        result = ExperimentService(_workspace()).evaluate(
            experiment_id,
            body.get("baseline_scores"),
            body.get("candidate_scores"),
        )
        return ok_response(result)
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Experiment not found: {experiment_id}")
    except (TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def _workbench():
    from nous_runtime.workspace.workbench import DeveloperWorkbench

    return DeveloperWorkbench(_workspace())


def _workbench_error(exc: Exception) -> dict[str, Any]:
    from nous_runtime.workspace.workbench import WorkbenchConflict

    code = "NOUS_WORKSPACE_CONFLICT" if isinstance(exc, WorkbenchConflict) else "NOUS_INVALID_REQUEST"
    return err_response(code, str(exc))


def handle_developer_workspace_files(params: dict[str, Any] | None = None) -> dict[str, Any]:
    values = params or {}
    try:
        return ok_response(_workbench().list_files(
            path=str(values.get("path") or "."),
            limit=int(values.get("limit") or 500),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_workspace_file(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_workbench().read_file(str(params.get("path") or "")))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_workspace_search(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_workbench().search(
            str(params.get("q") or ""),
            path=str(params.get("path") or "."),
            limit=int(params.get("limit") or 200),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_workspace_preview(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_workbench().preview_write(
            str(body.get("path") or ""),
            str(body.get("content") or ""),
            expected_sha256=str(body.get("expected_sha256") or ""),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_workspace_write(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_workbench().write_file(
            str(body.get("path") or ""),
            str(body.get("content") or ""),
            expected_sha256=str(body.get("expected_sha256") or ""),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_workspace_run(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_workbench().run_profile(
            str(body.get("profile") or ""),
            target=str(body.get("target") or ""),
            timeout_seconds=int(body.get("timeout_seconds") or 60),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return _workbench_error(exc)


def handle_developer_capabilities() -> dict[str, Any]:
    from nous_runtime.capability.availability import check_availability

    return ok_response(check_availability())

def handle_developer_model_lab(params: dict[str, Any] | None = None) -> dict[str, Any]:
    from nous_runtime.model_runtime.center import ModelCenterService
    from nous_runtime.model_runtime.observation_store import ModelObservationStore

    root = _workspace()
    center = ModelCenterService(root).snapshot()
    observations = ModelObservationStore(str(root))
    try:
        rankings = observations.get_model_rankings(min_samples=1, limit=50)
        recent = observations.query(limit=50)
        costs = observations.get_cost_summary()
    finally:
        observations.shutdown()
    return ok_response({
        **center,
        "rankings": rankings,
        "recent_observations": recent,
        "costs": costs,
        "evidence_status": "measured" if recent else "awaiting_observations",
    })


DEVELOPER_ROUTES = {
    ("GET", "/api/v1/developer/overview"): handle_developer_overview,
    ("GET", "/api/v1/developer/projects"): handle_developer_projects,
    ("GET", "/api/v1/developer/projects/{project_id}"): handle_developer_project,
    ("POST", "/api/v1/developer/projects"): handle_developer_project_create,
    ("POST", "/api/v1/developer/projects/{project_id}/action"): handle_developer_project_action,
    ("GET", "/api/v1/developer/runs"): handle_developer_runs,
    ("GET", "/api/v1/developer/experiments"): handle_developer_experiments,
    ("POST", "/api/v1/developer/experiments"): handle_developer_experiment_create,
    ("POST", "/api/v1/developer/experiments/{experiment_id}/evaluate"): handle_developer_experiment_evaluate,
    ("GET", "/api/v1/developer/model-lab"): handle_developer_model_lab,
    ("GET", "/api/v1/developer/capabilities"): handle_developer_capabilities,
    ("GET", "/api/v1/developer/workspace/files"): handle_developer_workspace_files,
    ("GET", "/api/v1/developer/workspace/file"): handle_developer_workspace_file,
    ("GET", "/api/v1/developer/workspace/search"): handle_developer_workspace_search,
    ("POST", "/api/v1/developer/workspace/preview"): handle_developer_workspace_preview,
    ("POST", "/api/v1/developer/workspace/write"): handle_developer_workspace_write,
    ("POST", "/api/v1/developer/workspace/run"): handle_developer_workspace_run,
}


DEVELOPER_GOVERNANCE = {
    ("POST", "/api/v1/developer/projects"): ("project.create", "local_write", "reversible"),
    ("POST", "/api/v1/developer/projects/{project_id}/action"): ("project.control", "local_write", "partially_reversible"),
    ("POST", "/api/v1/developer/experiments"): ("experiment.create", "local_write", "reversible"),
    ("POST", "/api/v1/developer/experiments/{experiment_id}/evaluate"): ("experiment.evaluate", "local_write", "reversible"),
    ("POST", "/api/v1/developer/workspace/write"): ("project.write_file", "local_write", "reversible"),
    ("POST", "/api/v1/developer/workspace/run"): ("project.run_tests", "local_write", "partially_reversible"),
}


__all__ = ["DEVELOPER_GOVERNANCE", "DEVELOPER_ROUTES"]
