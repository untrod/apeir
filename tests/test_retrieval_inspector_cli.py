import json

from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.project.memory import add_fact
from nous_runtime.retrieval.inspector import retrieval_diagnose, retrieval_snapshot


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    (ws / "memory").mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"name": "project_a"}), encoding="utf-8")
    return ws


def test_retrieval_inspector_reports_empty_state(tmp_path):
    ws = _workspace(tmp_path)

    snap = retrieval_snapshot(ws)

    assert snap["indexes"] == []
    assert snap["backends"]
    assert retrieval_diagnose(ws) == []


def test_retrieval_cli_rebuild_and_inspect(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    add_fact(ws, "project.language", "python", "scan")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    rebuild = runner.invoke(app, ["retrieval", "index", "rebuild", "--workspace-id", "workspace_a"])
    status = runner.invoke(app, ["retrieval", "index", "status", "--json"])
    inspect = runner.invoke(app, ["inspect", "retrieval", "--json"])

    assert rebuild.exit_code == 0
    assert "exported=1" in rebuild.stdout
    assert status.exit_code == 0
    assert json.loads(status.stdout)[-1]["state"] == "active"
    assert inspect.exit_code == 0
    assert json.loads(inspect.stdout)["indexes"]
