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
from nous_runtime.kernel.windows_sandbox import executable_path


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


def test_nous_persona_hides_provider_identity(tmp_path: Path) -> None:
    prompt = nous_system_prompt(workspace=str(tmp_path), agent_mode="agent")
    assert "You are Nous" in prompt
    assert "never identify yourself as DeepSeek" in prompt
    assert str(tmp_path) in prompt
    assert "request-scoped capabilities activated by an explicit user request" in prompt
    assert "not as unavailable" in prompt


def test_nous_persona_reports_explicit_workspace_effect_authorization(tmp_path: Path) -> None:
    prompt = nous_system_prompt(
        workspace=str(tmp_path),
        agent_mode="agent",
        mutation_authorized=True,
    )

    assert "explicitly authorizes the supplied governed effect tools" in prompt
    assert "create or update code/files" in prompt


def test_mutation_requires_an_explicit_request() -> None:
    assert mutation_is_explicit("请创建 report.txt")
    assert mutation_is_explicit("fix the failing tests")
    assert mutation_is_explicit("请联网搜索最新资料")
    assert mutation_is_explicit("run simulation sim-1")
    assert mutation_is_explicit("渲染文档 doc-1")
    assert not mutation_is_explicit("只读查看代码，不要修改")
    assert not mutation_is_explicit("what files are here?")
    assert not mutation_is_explicit("现在不能联网吗？")


def test_workspace_tools_list_read_search_and_write(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    listed = runtime.execute("list_workspace", {"path": ".", "max_depth": 1})
    read = runtime.execute("read_file", {"path": "source.txt"})
    searched = runtime.execute("search_workspace", {"query": "beta"})
    written = runtime.execute("write_file", {"path": "artifacts/result.txt", "content": "done"})

    assert listed["ok"] and any(item["path"] == "source.txt" for item in listed["entries"])
    assert read["ok"] and read["content"] == "alpha\nbeta"
    assert searched["ok"] and searched["matches"][0]["line"] == 2
    assert written["ok"] and (tmp_path / "artifacts" / "result.txt").read_text(encoding="utf-8") == "done"
    assert written["receipt_id"].startswith("receipt-")


def test_workspace_tools_batch_write_project_files(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    written = runtime.execute(
        "write_files",
        {
            "files": [
                {"path": "sample/main.py", "content": "print('ready')\n"},
                {"path": "sample/README.md", "content": "# Sample\n"},
            ]
        },
    )

    assert written["ok"]
    assert written["file_count"] == 2
    assert (tmp_path / "sample" / "main.py").is_file()


def test_workspace_tools_block_unapproved_mutation_and_escape(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path))
    denied = runtime.execute("write_file", {"path": "result.txt", "content": "no"})
    escaped = runtime.execute("read_file", {"path": "../outside.txt"})
    command = runtime.execute("run_command", {"command": "cmd /c whoami"})

    assert not denied["ok"]
    assert not escaped["ok"]
    assert not command["ok"]
    assert not (tmp_path / "result.txt").exists()


def test_workspace_command_rejects_shell_operators_and_absolute_paths(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    chained = runtime.execute("run_command", {"command": ["pytest", "&&", "whoami"]})
    escaped = runtime.execute("run_command", {"command": ["pytest", "C:\\Windows"]})

    assert not chained["ok"]
    assert not escaped["ok"]


@requires_strong_sandbox
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

    assert result["ok"] is True
    assert result["exit_code"] == 0


@requires_strong_sandbox
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

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["receipt_id"] != second["receipt_id"]


def test_batch_write_rejects_workspace_root_as_a_file(tmp_path: Path) -> None:
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)

    result = runtime.execute(
        "write_files",
        {"files": [{"path": "", "content": "invalid"}]},
    )

    assert result["ok"] is False
    assert "unique" in result["error"].lower()


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
    assert '"required":["path","content"]' in prompt
    assert '"content":"string"' in prompt
    assert parsed and parsed["name"] == "list_workspace"
    assert rejected is None
