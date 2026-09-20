from __future__ import annotations

from nous_runtime.api.developer_routes import (
    DEVELOPER_ROUTES,
    handle_developer_experiment_create,
    handle_developer_experiment_evaluate,
    handle_developer_experiments,
    handle_developer_model_lab,
    handle_developer_project_action,
    handle_developer_project_create,
    handle_developer_projects,
    handle_developer_runs,
    handle_developer_workspace_file,
    handle_developer_workspace_files,
    handle_developer_workspace_preview,
    handle_developer_workspace_search,
    handle_developer_workspace_write,
)
from nous_runtime.api.routes import route
from nous_runtime.events import EventStream, RunEvent


def test_developer_route_contract_is_registered():
    assert ("GET", "/api/v1/developer/projects") in DEVELOPER_ROUTES
    assert ("GET", "/api/v1/developer/runs") in DEVELOPER_ROUTES
    assert ("GET", "/api/v1/developer/model-lab") in DEVELOPER_ROUTES
    assert ("GET", "/api/v1/developer/workspace/files") in DEVELOPER_ROUTES
    assert ("POST", "/api/v1/developer/workspace/write") in DEVELOPER_ROUTES
    assert ("POST", "/api/v1/developer/workspace/run") in DEVELOPER_ROUTES
    assert ("POST", "/api/v1/developer/experiments/{experiment_id}/evaluate") in DEVELOPER_ROUTES


def test_run_center_reads_canonical_event_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    stream = EventStream(str(tmp_path))
    stream.emit(RunEvent(run_id="run_platform", task_id="task_platform", event_type="run.started"))
    stream.emit(RunEvent(run_id="run_platform", task_id="task_platform", event_type="run.completed"))

    response = handle_developer_runs()

    assert response["ok"] is True
    assert response["data"]["runs"][0]["run_id"] == "run_platform"
    assert response["data"]["runs"][0]["state"] == "COMPLETED"


def test_project_center_uses_durable_project_service(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    created = handle_developer_project_create({"name": "Kernel work", "description": "Ship evidence"})
    project_id = created["data"]["project_id"]

    started = handle_developer_project_action(project_id, {"action": "start"})
    listed = handle_developer_projects()

    assert started["ok"] is True
    assert started["data"]["status"] == "active"
    assert listed["data"]["projects"][0]["project_id"] == project_id


def test_model_lab_reports_empty_evidence_without_fabricating_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))

    response = handle_developer_model_lab()

    assert response["ok"] is True
    assert response["data"]["evidence_status"] == "awaiting_observations"
    assert response["data"]["rankings"] == []


def test_experiment_api_requires_real_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    created = handle_developer_experiment_create({
        "hypothesis": "Candidate improves quality",
        "baseline_name": "base",
        "candidate_name": "candidate",
    })
    experiment_id = created["data"]["experiment_id"]

    invalid = handle_developer_experiment_evaluate(experiment_id, {
        "baseline_scores": [0.5],
        "candidate_scores": [0.7],
    })
    valid = handle_developer_experiment_evaluate(experiment_id, {
        "baseline_scores": [0.5, 0.5, 0.5, 0.5, 0.5],
        "candidate_scores": [0.7, 0.7, 0.7, 0.7, 0.7],
    })
    snapshot = handle_developer_experiments()

    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "NOUS_INVALID_REQUEST"
    assert valid["ok"] is True
    assert snapshot["data"]["summary"]["benchmarked"] == 1


def test_v2_routes_are_not_rewritten_to_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    response = route("GET", "/api/v2/experiments")

    assert response["ok"] is True
    assert response["meta"]["api_version"] == "v2"


def test_developer_workspace_api_read_search_preview_and_write(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    source = tmp_path / "hello.py"
    source.write_text("print('before')\n", encoding="utf-8")

    listing = handle_developer_workspace_files({})
    read = handle_developer_workspace_file({"path": "hello.py"})
    search = handle_developer_workspace_search({"q": "before"})
    preview = handle_developer_workspace_preview({
        "path": "hello.py",
        "content": "print('after')\n",
        "expected_sha256": read["data"]["sha256"],
    })
    written = handle_developer_workspace_write({
        "path": "hello.py",
        "content": "print('after')\n",
        "expected_sha256": read["data"]["sha256"],
    })

    assert listing["data"]["files"][0]["path"] == "hello.py"
    assert search["data"]["matches"][0]["line"] == 1
    assert preview["data"]["changed"] is True
    assert written["ok"] is True
    assert written["data"]["run_id"].startswith("workbench-write-")
    assert source.read_text(encoding="utf-8") == "print('after')\n"


def test_developer_workspace_api_reports_stale_write_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    source = tmp_path / "hello.py"
    source.write_text("one", encoding="utf-8")
    read = handle_developer_workspace_file({"path": "hello.py"})
    source.write_text("two", encoding="utf-8")

    response = handle_developer_workspace_write({
        "path": "hello.py",
        "content": "three",
        "expected_sha256": read["data"]["sha256"],
    })

    assert response["ok"] is False
    assert response["error"]["code"] == "NOUS_WORKSPACE_CONFLICT"