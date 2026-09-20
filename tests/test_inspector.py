# -*- coding: utf-8 -*-
"""Runtime Inspector tests."""

import json
from pathlib import Path


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / ".nous"
    memory = ws / "memory"
    memory.mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"name": "inspect-test"}), encoding="utf-8")
    (ws / "config.json").write_text("{}", encoding="utf-8")
    (ws / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task_1",
                        "description": "Run model",
                        "status": "failed",
                        "capability_id": "model.reason",
                        "observation_ids": ["obs_1"],
                        "error": "timeout",
                    }
                ],
                "plans": [
                    {
                        "plan_id": "plan_1",
                        "goal_id": "goal_1",
                        "status": "failed",
                        "task_ids": ["task_1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    for filename in (
        "timeline.jsonl",
        "events.jsonl",
        "decisions.jsonl",
        "summaries.jsonl",
        "facts.jsonl",
        "experiences.jsonl",
        "artifacts.jsonl",
    ):
        (memory / filename).write_text("", encoding="utf-8")
    return ws


def test_snapshot_empty_workspace_does_not_crash(tmp_path, monkeypatch):
    from nous_runtime.project.workspace import init_workspace
    from nous_runtime.inspector import snapshot

    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    snap = snapshot()
    data = snap.to_dict()

    assert data["runtime"]["workspace"].endswith(".nous")
    assert "memory" in data
    assert isinstance(data["tasks"], list)


def test_diagnose_reports_corrupt_memory_and_failed_task(tmp_path, monkeypatch):
    from nous_runtime.inspector import diagnose, snapshot

    ws = _workspace(tmp_path)
    (ws / "memory" / "events.jsonl").write_text(
        json.dumps(
            {
                "memory_id": "mem_obs_1",
                "record_type": "event",
                "observation_id": "obs_1",
                "task_id": "task_1",
                "capability_id": "model.reason",
                "provider_id": "demo",
                "status": "failed",
                "detail": "provider timeout",
            }
        )
        + "\nnot-json\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    snap = snapshot()
    findings = diagnose(snap)
    codes = {f.code for f in findings}

    assert any(o.observation_id == "obs_1" for o in snap.observations)
    assert "TASK_FAILED" in codes
    assert "OBSERVATION_FAILED" in codes
    assert "MEMORY_INVALID_RECORD" in codes
    severities = [finding.severity for finding in findings]
    assert severities == sorted(
        severities,
        key={"error": 0, "warning": 1, "info": 2}.get,
    )


def test_memory_supersedes_diagnostics(tmp_path, monkeypatch):
    from nous_runtime.inspector import diagnose, snapshot

    ws = _workspace(tmp_path)
    facts = [
        {
            "memory_id": "mem_a",
            "record_type": "fact",
            "stable_key": "project.language",
            "key": "project.language",
            "value": "python",
            "supersedes": "missing",
        },
        {
            "memory_id": "mem_b",
            "record_type": "fact",
            "stable_key": "project.language",
            "key": "project.language",
            "value": "kotlin",
            "supersedes": "mem_a",
        },
    ]
    (ws / "memory" / "facts.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in facts),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    codes = {f.code for f in diagnose(snapshot())}

    assert "MEMORY_SUPERSEDES_BROKEN" in codes
    assert "MEMORY_STABLE_KEY_CONFLICT" in codes


def test_api_inspector_routes(tmp_path, monkeypatch):
    from nous_runtime.api.routes import route

    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    runtime = route("GET", "/api/inspector/runtime")
    diagnostics = route("GET", "/api/inspector/diagnostics")

    assert runtime["ok"] is True
    assert runtime["data"]["workspace"].endswith(".nous")
    assert diagnostics["ok"] is True
    assert isinstance(diagnostics["data"], list)


def test_shell_inspect_command(tmp_path, monkeypatch):
    from nous_runtime.cli.shell_v2 import COMMANDS

    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = COMMANDS["inspect"]["fn"]([])
    diagnose = COMMANDS["inspect"]["fn"](["diagnose"])

    assert "Inspector Snapshot" in result
    assert "TASK_FAILED" in diagnose


def test_cli_inspect_json(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from nous_runtime.cli.main import app

    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["inspect", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["runtime"]["workspace"].endswith(".nous")
    assert "counts" in data
