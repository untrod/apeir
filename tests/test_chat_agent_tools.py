from __future__ import annotations

from pathlib import Path
import os
import sys

import pytest

from nous_runtime.chat.agent_tools import (
    WorkspaceToolRuntime,
    mutation_is_explicit,
    parse_text_tool_call,
    tool_protocol_prompt,
)
from nous_runtime.persona import nous_system_prompt
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.governance.cli import _build_context
from nous_runtime.workspace.proposals import WorkspaceProposalService


@pytest.fixture
def governed_tools(tmp_path):
    gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous"))
    service = WorkspaceProposalService(tmp_path, gate=gate)
    runtime = WorkspaceToolRuntime(
        str(tmp_path),
        allow_mutations=True,
        subject_id="agent.test.workspace",
        proposal_service=service,
    )
    return runtime, service


def apply_reviewed(service, result):
    assert result["error_code"] == "NOUS_APPROVAL_REQUIRED"
    service.broker.respond_operation(
        result["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    return service.apply(result["proposal_id"])


@pytest.mark.parametrize("reserved", [".nous", ".git", "nested/.NOUS"])
def test_ordinary_agent_context_excludes_runtime_private_state(tmp_path, reserved):
    private = tmp_path / reserved / "protected.txt"
    private.parent.mkdir(parents=True)
    private.write_text("FAKE_ONLY_PRIVATE_MARKER")
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    for name, arguments in (
        (
            "read_file",
            {"path": f"{reserved}/protected.txt", "protect_runtime_state": False},
        ),
        ("list_workspace", {"path": reserved}),
        ("search_workspace", {"path": reserved, "query": "FAKE_ONLY"}),
        ("find_workspace", {"path": reserved, "pattern": "*.txt"}),
    ):
        result = runtime.execute(name, arguments)
        assert result["ok"] is False
        assert "FAKE_ONLY_PRIVATE_MARKER" not in str(result)


def test_agent_scan_and_read_exclude_aliases_into_private_state(tmp_path):
    private = tmp_path / ".nous" / "protected.txt"
    private.parent.mkdir()
    private.write_text("FAKE_ONLY_PRIVATE_MARKER")
    (tmp_path / "ordinary.txt").write_text("ordinary")
    try:
        (tmp_path / "alias.txt").symlink_to(private)
    except OSError:
        pytest.skip("This platform does not permit symlink creation")
    runtime = WorkspaceToolRuntime(str(tmp_path))
    assert runtime.execute("read_file", {"path": "alias.txt"})["ok"] is False
    assert runtime.execute("search_workspace", {"query": "FAKE_ONLY"})["matches"] == []
    assert [
        entry["path"] for entry in runtime.execute("list_workspace", {})["entries"]
    ] == ["ordinary.txt"]
    assert [
        entry["path"]
        for entry in runtime.execute("find_workspace", {"pattern": "*.txt"})["matches"]
    ] == ["ordinary.txt"]


def test_nous_persona_hides_provider_identity(tmp_path: Path) -> None:
    prompt = nous_system_prompt(workspace=str(tmp_path), agent_mode="agent")
    assert "You are Nous" in prompt
    assert "never identify yourself as DeepSeek" in prompt
    assert str(tmp_path) in prompt
    assert "cannot grant execution authority" in prompt
    assert "current Governance admission" in prompt


def test_nous_persona_reports_explicit_workspace_effect_authorization(
    tmp_path: Path,
) -> None:
    prompt = nous_system_prompt(
        workspace=str(tmp_path),
        agent_mode="agent",
        mutation_authorized=True,
    )

    assert "File tools prepare proposals" in prompt
    assert "Only valid approval through Governance" in prompt


def test_mutation_requires_an_explicit_request() -> None:
    assert mutation_is_explicit("请创建 report.txt")
    assert mutation_is_explicit("fix the failing tests")
    assert mutation_is_explicit(
        "Find the bug, make the smallest correct change, and run the relevant test."
    )
    assert mutation_is_explicit(
        "Make the smallest correct change. Do not modify unrelated code."
    )
    assert mutation_is_explicit(
        "Create research-report.md. Do not modify any other file."
    )
    assert mutation_is_explicit("创建 research-report.md，不要修改任何其他文件。")
    assert mutation_is_explicit("请联网搜索最新资料")
    assert mutation_is_explicit("run simulation sim-1")
    assert mutation_is_explicit("渲染文档 doc-1")
    assert not mutation_is_explicit("只读查看代码，不要修改")
    assert not mutation_is_explicit("Do not modify code.")
    assert not mutation_is_explicit("what files are here?")
    assert not mutation_is_explicit("现在不能联网吗？")


def test_workspace_tools_list_read_search_and_write(
    tmp_path: Path, governed_tools
) -> None:
    (tmp_path / "source.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    runtime, service = governed_tools

    listed = runtime.execute("list_workspace", {"path": ".", "max_depth": 1})
    read = runtime.execute("read_file", {"path": "source.txt"})
    searched = runtime.execute("search_workspace", {"query": "beta"})
    found = runtime.execute("find_workspace", {"pattern": "*.txt"})
    written = runtime.execute(
        "write_file", {"path": "artifacts/result.txt", "content": "done"}
    )

    assert listed["ok"] and any(
        item["path"] == "source.txt" for item in listed["entries"]
    )
    assert read["ok"] and read["content"] == "alpha\nbeta"
    assert searched["ok"] and searched["matches"][0]["line"] == 2
    assert found["ok"] and found["matches"][0]["path"] == "source.txt"
    assert not written["ok"] and not (tmp_path / "artifacts" / "result.txt").exists()
    applied = apply_reviewed(service, written)
    assert applied["applied"] and applied["verification"]["verdict"] == "MATCH"
    assert (tmp_path / "artifacts" / "result.txt").read_text() == "done"
    assert applied["authorization_id"] == written["authorization_id"]
    assert applied["kernel_traversed"] is False


def test_workspace_tools_batch_write_project_files(
    tmp_path: Path, governed_tools
) -> None:
    runtime, service = governed_tools
    written = runtime.execute(
        "write_files",
        {
            "files": [
                {"path": "sample/main.py", "content": "print('ready')\n"},
                {"path": "sample/README.md", "content": "# Sample\n"},
            ]
        },
    )

    assert not written["ok"]
    assert not (tmp_path / "sample" / "main.py").exists()
    applied = apply_reviewed(service, written)
    assert applied["applied"] and applied["verification"]["verdict"] == "MATCH"
    assert written["file_count"] == 2
    assert (tmp_path / "sample" / "main.py").is_file()


def test_workspace_tools_patch_mkdir_move_and_remove_with_change_records(
    tmp_path: Path,
    governed_tools,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("before\n", encoding="utf-8")
    runtime, service = governed_tools
    runtime.execute("read_file", {"path": "source.txt"})

    patched = runtime.execute(
        "patch_file",
        {"path": "source.txt", "expected": "before", "replacement": "after"},
    )
    made = runtime.execute("make_directory", {"path": "archive"})
    moved = runtime.execute(
        "move_path",
        {"source": "source.txt", "destination": "archive/source.txt"},
    )
    removed = runtime.execute("remove_path", {"path": "archive/source.txt"})

    assert not patched["ok"] and target.read_text() == "before\n"
    assert all(
        not result["ok"]
        and result["error_code"] == "NOUS_UNSUPPORTED_GOVERNED_OPERATION"
        for result in (made, moved, removed)
    )
    assert not (tmp_path / "archive").exists()
    assert apply_reviewed(service, patched)["applied"]
    assert target.read_text() == "after\n"


def test_workspace_patch_fails_closed_on_stale_or_ambiguous_context(
    tmp_path: Path,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    ambiguous = runtime.execute(
        "patch_file",
        {"path": "source.txt", "expected": "same", "replacement": "changed"},
    )
    stale = runtime.execute(
        "patch_file",
        {
            "path": "source.txt",
            "expected": "same\n",
            "replacement": "changed\n",
            "expected_sha256": "0" * 64,
        },
    )

    assert ambiguous["ok"] is False
    assert stale["ok"] is False
    assert target.read_text(encoding="utf-8") == "same\nsame\n"


def test_workspace_tools_block_unapproved_mutation_and_escape(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path))
    denied = runtime.execute("write_file", {"path": "result.txt", "content": "no"})
    escaped = runtime.execute("read_file", {"path": "../outside.txt"})
    command = runtime.execute("run_command", {"command": "cmd /c whoami"})

    assert not denied["ok"]
    assert not escaped["ok"]
    assert not command["ok"]
    assert not (tmp_path / "result.txt").exists()


def test_workspace_command_rejects_shell_operators_and_absolute_paths(
    tmp_path: Path,
) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    chained = runtime.execute("run_command", {"command": ["pytest", "&&", "whoami"]})
    escaped = runtime.execute("run_command", {"command": ["pytest", "C:\\Windows"]})

    assert not chained["ok"]
    assert not escaped["ok"]


def test_workspace_command_resolves_executable_before_strict_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    executable_dir = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", executable_dir + os.pathsep + os.environ.get("PATH", ""))
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    result = runtime.execute(
        "run_command",
        {"command": ["python", "-m", "compileall", "-q", "sample.py"]},
    )

    assert result["ok"] is False
    assert result["error_code"] == "NOUS_UNSUPPORTED_GOVERNED_OPERATION"
    assert not (tmp_path / "__pycache__").exists()


def test_workspace_command_can_be_rerun_after_a_workspace_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    executable_dir = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", executable_dir + os.pathsep + os.environ.get("PATH", ""))
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    command = {"command": ["python", "-m", "compileall", "-q", "sample.py"]}

    first = runtime.execute("run_command", command)
    second = runtime.execute("run_command", command)

    assert first["ok"] is False and second["ok"] is False
    assert (
        first["error_code"]
        == second["error_code"]
        == "NOUS_UNSUPPORTED_GOVERNED_OPERATION"
    )
    assert not (tmp_path / "__pycache__").exists()


def test_batch_write_rejects_workspace_root_as_a_file(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    result = runtime.execute(
        "write_files",
        {"files": [{"path": "", "content": "invalid"}]},
    )

    assert result["ok"] is False
    assert "cannot be written" in result["error"].lower()
    assert tmp_path.is_dir()
    assert not any(path.is_file() for path in tmp_path.iterdir())


def test_text_tool_protocol_is_bounded_to_declared_tools(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    prompt = tool_protocol_prompt(runtime.specifications())
    parsed = parse_text_tool_call(
        'NOUS_TOOL_CALL {"name":"list_workspace","arguments":{"path":"."}}',
        {"list_workspace", "read_file", "search_workspace"},
    )
    rejected = parse_text_tool_call(
        '{"name":"delete_file","arguments":{"path":"important.txt"}}',
        {"list_workspace", "read_file", "search_workspace"},
    )

    assert "list_workspace" in prompt
    assert '"name":"write_file"' in prompt
    assert "prefer patch_file" in prompt
    assert '"required":["path","content"]' in prompt
    assert '"content":"string"' in prompt
    assert parsed and parsed["name"] == "list_workspace"
    assert rejected is None
