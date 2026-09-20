from typer.testing import CliRunner

from nous_runtime.cli import runtime_intelligence
from nous_runtime.cli.main import app
from nous_runtime.task import TaskManager


runner = CliRunner()


def test_routing_test_cli() -> None:
    result = runner.invoke(app, ["routing", "test", "Write Python code"])

    assert result.exit_code == 0, result.output
    assert "Task      coding" in result.output
    assert "Selected" in result.output
    assert "Reason" in result.output


def test_intelligence_analyze_reports_missing_task() -> None:
    result = runner.invoke(app, ["intelligence", "analyze", "missing-task"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_intelligence_analyze_cli(monkeypatch) -> None:
    manager = TaskManager()
    task = manager.create("Debug Python code")
    monkeypatch.setattr("nous_runtime.task.cli.get_task_manager", lambda: manager)

    result = runner.invoke(app, ["intelligence", "analyze", task.id])

    assert result.exit_code == 0, result.output
    assert "Type          coding" in result.output
    assert "Capabilities  coding, reasoning" in result.output
    assert "Suggested" in result.output


def test_routing_simulate_cli() -> None:
    result = runner.invoke(app, ["routing", "simulate", "--json"])

    assert result.exit_code == 0, result.output
    payload = __import__("json").loads(result.output)
    assert len(payload) == 8
    assert {item["fixture"] for item in payload} >= {
        "coding",
        "mathematics",
        "vision",
        "unknown_cold_start",
    }


def test_routing_compare_and_explain_cli(monkeypatch, tmp_path) -> None:
    manager = TaskManager()
    task = manager.create("Debug Python code")
    history_path = tmp_path / "routing.jsonl"
    monkeypatch.setattr("nous_runtime.task.cli.get_task_manager", lambda: manager)
    monkeypatch.setattr(
        runtime_intelligence,
        "_routing_history_path",
        lambda: history_path,
    )

    compared = runner.invoke(app, ["routing", "compare", task.id])

    assert compared.exit_code == 0, compared.output
    decision_line = next(
        line for line in compared.output.splitlines() if line.startswith("Decision")
    )
    decision_id = decision_line.split()[-1]
    explained = runner.invoke(app, ["routing", "explain", decision_id])
    assert explained.exit_code == 0, explained.output
    assert f"Decision    {decision_id}" in explained.output
    assert "Policy" in explained.output
