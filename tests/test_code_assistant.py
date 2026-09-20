from __future__ import annotations

from nous_runtime.agents.external.models import AgentRunResult
from nous_runtime.code_assistant import CodeAssistant, PatchScopeError, RepositoryAnalyzer, validate_diff_scope


class MockCodingAgent:
    def __init__(self, workspace, *, outside=False, fail=False):
        self.workspace = workspace
        self.outside = outside
        self.fail = fail
        self.requests = []

    def execute(self, request, context):
        self.requests.append((request, context))
        (self.workspace / "app.py").write_text("print('changed')\n", encoding="utf-8")
        if self.outside:
            (self.workspace / "secret.txt").write_text("out of scope", encoding="utf-8")
        return AgentRunResult(run_id=request.run_id, agent_id="agent.mock", status="FAILED" if self.fail else "COMPLETED", exit_code=1 if self.fail else 0, changed_files=("app.py",), errors=("failed",) if self.fail else ())


def repository(tmp_path):
    (tmp_path / "app.py").write_text("print('before')\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1.0.0'\n", encoding="utf-8")


def test_repository_discovery_and_test_selection(tmp_path):
    repository(tmp_path)
    profile = RepositoryAnalyzer().analyze(tmp_path)
    assert profile.languages == ("python",)
    assert "pyproject.toml" in profile.dependency_files
    assert RepositoryAnalyzer.select_tests(profile) == (("python", "-m", "pytest", "-q"),)
    assert all(isinstance(command, tuple) for command in RepositoryAnalyzer.select_static_analysis(profile))


def test_controlled_code_change_success(tmp_path):
    repository(tmp_path)
    agent = MockCodingAgent(tmp_path)
    assistant = CodeAssistant(tmp_path, agent, isolated_workspace=True)
    plan = assistant.plan("Update output", allowed_files=("app.py",))
    result = assistant.execute(plan)
    assert result.ok and result.changed_files == ("app.py",)
    request, context = agent.requests[0]
    assert request.approval_policy == "ask_per_command"
    assert context.input_files == ("app.py",)
    assert ["python", "-m", "pytest", "-q"] in request.plan["test_commands"]


def test_non_isolated_workspace_is_denied(tmp_path):
    repository(tmp_path)
    assistant = CodeAssistant(tmp_path, MockCodingAgent(tmp_path))
    result = assistant.execute(assistant.plan("Change", allowed_files=("app.py",)))
    assert not result.ok and result.status == "denied"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('before')\n"


def test_scope_violation_rolls_back_all_changes(tmp_path):
    repository(tmp_path)
    assistant = CodeAssistant(tmp_path, MockCodingAgent(tmp_path, outside=True), isolated_workspace=True)
    result = assistant.execute(assistant.plan("Change", allowed_files=("app.py",)))
    assert not result.ok and result.status == "scope_violation"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('before')\n"
    assert not (tmp_path / "secret.txt").exists()


def test_agent_failure_rolls_back(tmp_path):
    repository(tmp_path)
    assistant = CodeAssistant(tmp_path, MockCodingAgent(tmp_path, fail=True), isolated_workspace=True)
    result = assistant.execute(assistant.plan("Change", allowed_files=("app.py",)))
    assert not result.ok
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('before')\n"


def test_allowed_file_and_diff_paths_fail_closed(tmp_path):
    repository(tmp_path)
    assistant = CodeAssistant(tmp_path, MockCodingAgent(tmp_path), isolated_workspace=True)
    try:
        assistant.plan("Escape", allowed_files=("../private.txt",))
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("workspace escape was accepted")
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert validate_diff_scope(diff, ("app.py",)) == ("app.py",)
    with __import__('pytest').raises(PatchScopeError):
        validate_diff_scope(diff.replace("b/app.py", "b/secret.txt"), ("app.py",))