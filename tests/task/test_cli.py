"""Execution Runtime task CLI compatibility tests."""

import json

from typer.testing import CliRunner

from nous_runtime.cli.main import app


def test_task_cli_create_list_show_and_status(tmp_path, monkeypatch):
    (tmp_path / ".nous").mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "Incident analysis",
            "--description",
            "Inspect the failure",
            "--priority",
            "HIGH",
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    payload = json.loads(created.stdout)
    task_id = payload["id"]
    assert payload["status"] == "CREATED"
    assert payload["priority"] == "HIGH"

    listed = runner.invoke(app, ["task", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)[0]["id"] == task_id

    shown = runner.invoke(app, ["task", "show", task_id, "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["description"] == "Inspect the failure"

    status = runner.invoke(app, ["task", "status", task_id, "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout) == {"task_id": task_id, "status": "CREATED"}


def test_task_cli_preserves_existing_submit_command():
    result = CliRunner().invoke(app, ["task", "submit", "--help"])

    assert result.exit_code == 0
    assert "Capability ID" in result.stdout
