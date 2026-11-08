from __future__ import annotations

from types import SimpleNamespace

from nous_runtime.evaluation.validators.test_validator import TestValidator


def test_test_evaluation_never_starts_a_host_test_process(tmp_path, monkeypatch):
    calls = []

    def host_call(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="1 passed in 0.01s\n", stderr="")

    monkeypatch.setattr("subprocess.run", host_call)
    result = TestValidator().validate(
        None, {"cwd": str(tmp_path), "test_path": "tests"}
    )
    assert calls == [], (
        "Evaluation must inspect an original test Run, not launch host code"
    )
    assert not result[0].passed


def test_default_evaluation_never_starts_any_host_checker(tmp_path, monkeypatch):
    from nous_runtime.evaluation.evaluator import EvaluationEngine

    calls = []
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: calls.append(a))
    record = EvaluationEngine(workspace=str(tmp_path)).evaluate(
        target_type="project", target_id="fixture", persist=False
    )
    assert calls == []
    assert not any(
        item.passed for dimension in record.dimensions for item in dimension.evidence
    )
    assert record.status != "pass"


def test_serialized_stdout_is_not_a_test_receipt(tmp_path):
    result = TestValidator(workspace=str(tmp_path)).validate(
        None,
        {
            "stdout": "2000 passed",
            "exit_code": 0,
            "test_counts": {"passed": 2000},
            "test_run_id": "missing-original-run",
        },
    )[0]
    assert not result.passed
    assert result.detail["test_counts"] is None


def test_foreign_workspace_run_is_not_evidence_here(tmp_path):
    from nous_runtime.events import EventStream, RunEvent, RunState

    other = tmp_path / "other"
    other.mkdir()
    events = EventStream(str(other))
    events.create_run("foreign-test-run")
    events.emit(
        RunEvent(
            run_id="foreign-test-run",
            event_type="test.completed",
            actor="developer.workbench",
            payload={"profile": "pytest", "exit_code": 0, "ok": True},
        )
    )
    events.emit_state_change("foreign-test-run", RunState.COMPLETED)
    local = tmp_path / "local"
    local.mkdir()
    result = TestValidator(workspace=str(local)).validate(
        None, {"test_run_id": "foreign-test-run"}
    )[0]
    assert not result.passed and result.detail["test_counts"] is None
