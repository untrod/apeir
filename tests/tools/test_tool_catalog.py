from __future__ import annotations

from typer.testing import CliRunner

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.extensions.models import ToolSpec
from nous_runtime.events import RunState
from nous_runtime.tools import CATALOG_EXPAND_TOOL, ToolCatalog, ToolDefinition
from nous_runtime.tools.cli import tools_app
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness


class StubRuntime:
    def __init__(self):
        self.calls = []

    def specifications(self):
        return (
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
        )

    def execute(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return {"ok": True, "content": "value"}


def test_catalog_keeps_schemas_behind_category_expansion():
    runtime = StubRuntime()
    catalog = ToolCatalog()
    catalog.register_runtime(runtime)

    categories = catalog.categories()
    summaries = catalog.discover(category="files")
    expanded = catalog.execute(CATALOG_EXPAND_TOOL, {"category": "files"})

    assert categories[0]["category"] == "files"
    assert categories[0]["authority"] == "none"
    assert "input_schema" not in summaries[0]
    assert expanded["ok"] is True
    assert expanded["authority"] == "none"
    assert expanded["tools"][0]["input_schema"]["required"] == ["path"]
    assert [item["function"]["name"] for item in catalog.prompt_specifications()] == [
        CATALOG_EXPAND_TOOL
    ]


def test_catalog_delegates_execution_without_becoming_authority():
    runtime = StubRuntime()
    catalog = ToolCatalog()
    catalog.register_runtime(runtime)

    result = catalog.execute("read_file", {"path": "README.md"})

    assert result == {"ok": True, "content": "value"}
    assert runtime.calls == [("read_file", {"path": "README.md"})]
    assert catalog.require("read_file").metadata["authority"] == "none"


def test_tool_metadata_cannot_claim_authority():
    definition = ToolDefinition(
        tool_id="untrusted_tool",
        description="Untrusted tool metadata",
        input_schema={"type": "object"},
        metadata={"authority": "kernel", "reported_safe": True},
    )

    assert definition.summary()["metadata"]["authority"] == "none"


def test_read_only_workspace_catalog_does_not_advertise_mutations(tmp_path):
    catalog = ToolCatalog()
    catalog.register_runtime(WorkspaceToolRuntime(str(tmp_path), allow_mutations=False))

    identifiers = {item["tool_id"] for item in catalog.discover()}

    assert "read_file" in identifiers
    assert "write_file" not in identifiers
    assert "run_command" not in identifiers


def test_extension_and_mcp_tools_are_normalized_and_still_delegated():
    calls = []
    catalog = ToolCatalog()
    catalog.register_extension_tools(
        "example.mcp",
        (
            ToolSpec(
                name="lookup",
                description="Look up an external record",
                input_schema={"type": "object"},
                effect="unknown",
                protocol="mcp",
                operation="tools/call:lookup",
            ),
        ),
        executor=lambda extension_id, name, arguments: (
            calls.append((extension_id, name, dict(arguments))) or {"ok": True}
        ),
    )

    item = catalog.discover(category="mcp")[0]
    result = catalog.execute(item["tool_id"], {"key": "a"})

    assert item["effect_class"] == "unknown"
    assert item["approval_policy"] == "kernel_required"
    assert item["metadata"]["authority"] == "none"
    assert result["ok"] is True
    assert calls == [("example.mcp", "lookup", {"key": "a"})]


def test_work_loop_can_expand_then_invoke_a_catalog_tool(tmp_path):
    runtime = StubRuntime()
    catalog = ToolCatalog()
    catalog.register_runtime(runtime)
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one file")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Load file tool schemas",
                tool_name=CATALOG_EXPAND_TOOL,
                tool_arguments={"category": "files"},
            ),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Read the selected file",
                tool_name="read_file",
                tool_arguments={"path": "README.md"},
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "The file was inspected",
                output="done",
            ),
        )
    )

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=catalog,
    )

    assert completed.state is RunState.COMPLETED
    assert runtime.calls == [("read_file", {"path": "README.md"})]
    assert completed.observations[0]["result"]["tools"][0]["tool_id"] == "read_file"
    assert completed.loaded_tools["read_file"]["input_schema"]["required"] == ["path"]
    restored = WorkHarness(tmp_path).require(created.run_id)
    assert "read_file" in restored.loaded_tools


def test_catalog_expansion_cannot_complete_a_plan_step(tmp_path):
    runtime = StubRuntime()
    catalog = ToolCatalog()
    catalog.register_runtime(runtime)
    harness = WorkHarness(tmp_path)
    created = harness.create("Fix code in this project")
    execute_step = created.plan.require_task("execute_1")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Load file tools",
                tool_name=CATALOG_EXPAND_TOOL,
                tool_arguments={"category": "files"},
                step_id=execute_step.task_id,
            ),
            WorkDecision(
                DecisionStatus.BLOCKED,
                "Stop after checking discovery semantics",
            ),
        )
    )

    blocked = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=catalog,
    )

    assert blocked.plan.require_task(execute_step.task_id).status.value == "pending"
    assert blocked.observations[0]["step_id"] == ""


def test_work_loop_rejects_undisclosed_catalog_tool(tmp_path):
    runtime = StubRuntime()
    catalog = ToolCatalog()
    catalog.register_runtime(runtime)
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect a file")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Attempt an undisclosed tool",
                tool_name="read_file",
                tool_arguments={"path": "README.md"},
            ),
            WorkDecision(DecisionStatus.BLOCKED, "Stop after disclosure check"),
        )
    )

    blocked = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=catalog,
    )

    assert blocked.observations[0]["ok"] is False
    assert "catalog_expand" in blocked.observations[0]["result"]["error"]
    assert runtime.calls == []


def test_tools_cli_lists_capability_categories(tmp_path):
    result = CliRunner().invoke(
        tools_app,
        ["--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    assert '"category": "files"' in result.stdout
