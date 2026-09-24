from __future__ import annotations

from pathlib import Path

from nous_runtime.events import RunState
from nous_runtime.skills import SkillToolRuntime
from nous_runtime.tools import CATALOG_EXPAND_TOOL, ToolCatalog
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness

from tests.skills.test_skill_registry import make_skill


def test_work_checkpoint_retains_explicitly_loaded_skill(tmp_path: Path):
    make_skill(tmp_path / ".nous" / "skills" / "code-helper")
    tools = ToolCatalog()
    tools.register_runtime(SkillToolRuntime(tmp_path), provider_id="skill-registry")
    harness = WorkHarness(tmp_path)
    created = harness.create("Review the repository")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Load the Skill tool schemas",
                tool_name=CATALOG_EXPAND_TOOL,
                tool_arguments={"category": "skill"},
            ),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Load the selected review Skill",
                tool_name="skill_load",
                tool_arguments={"skill_id": "code-helper"},
            ),
            WorkDecision(
                DecisionStatus.BLOCKED,
                "Stop after checking durable Skill disclosure",
            ),
        )
    )

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
    )
    restored = WorkHarness(tmp_path).require(created.run_id)
    context = WorkHarness(tmp_path).context_for(restored)

    assert completed.state is RunState.BLOCKED
    assert "code-helper" in restored.loaded_skills
    assert context.loaded_skills[0]["instructions"].startswith("Read relevant code")
    assert all(item["step_id"] == "" for item in restored.observations)
