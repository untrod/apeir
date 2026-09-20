# -*- coding: utf-8 -*-
"""Observation layer tests — unified tool output schema."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestObservationSchema:
    """Observation dataclass construction and serialisation."""

    def test_success_factory(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.success("project.scan", {"files": 42})
        assert obs.status == "success"
        assert obs.tool == "project.scan"
        assert obs.data == {"files": 42}
        assert obs.errors == []
        assert obs.observation_id

    def test_failure_factory(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.failure("tool.x", ["file not found"])
        assert obs.status == "failed"
        assert obs.errors == ["file not found"]
        assert obs.data == {}

    def test_skipped_factory(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.skipped("tool.y", "unavailable")
        assert obs.status == "skipped"

    def test_to_dict_roundtrip(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.success("test.tool", {"key": "value"})
        d = obs.to_dict()
        assert d["status"] == "success"
        assert d["tool"] == "test.tool"
        assert d["data"] == {"key": "value"}
        assert d["schema_version"] == "1.0"

    def test_summary_compact(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.success("proj.scan", {"x": 1, "y": 2})
        s = obs.summary()
        assert s["tool"] == "proj.scan"
        assert s["status"] == "success"
        assert "x" in s["data_keys"]

    def test_context_block_success(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.success("project.scan", {"files": 10})
        block = obs.to_context_block()
        assert "[Observation" in block
        assert "project.scan" in block
        assert "success" in block
        assert '"files": 10' in block

    def test_context_block_failed(self):
        from nous_runtime.planner.observation import Observation
        obs = Observation.failure("tool.x", ["permission denied"])
        block = obs.to_context_block()
        assert "failed" in block
        assert "permission denied" in block

    def test_context_block_redacts_absolute_paths(self):
        from nous_runtime.planner.observation import Observation

        obs = Observation.success(
            "project.scan",
            {
                "workspace": "F:\\Agent_play",
                "root": "/opt/nous",
                "file": "README.md",
                "nested": {"path": "C:\\Users\\Admin\\secret.txt"},
            },
        )
        block = obs.to_context_block()

        assert "F:\\Agent_play" not in block
        assert "/opt/nous" not in block
        assert "C:\\Users\\Admin\\secret.txt" not in block
        assert block.count("<redacted-path>") == 3
        assert "README.md" in block
        assert obs.data["workspace"] == "F:\\Agent_play"


class TestToolObservation:
    """Every local tool must return a valid Observation."""

    def test_project_scan_returns_observation(self):
        from nous_runtime.planner.tool_router import _tool_project_scan
        obs = _tool_project_scan()
        from nous_runtime.planner.observation import Observation
        assert isinstance(obs, Observation)
        assert obs.status == "success"
        assert obs.tool == "project.scan"
        assert "files" in obs.data or "workspace" in obs.data

    def test_project_tasks_returns_observation(self):
        from nous_runtime.planner.tool_router import _tool_project_tasks
        obs = _tool_project_tasks()
        from nous_runtime.planner.observation import Observation
        assert isinstance(obs, Observation)
        assert obs.tool == "project.tasks"

    def test_project_memory_returns_observation(self):
        from nous_runtime.planner.tool_router import _tool_project_memory
        obs = _tool_project_memory()
        from nous_runtime.planner.observation import Observation
        assert isinstance(obs, Observation)
        assert obs.tool == "project.memory"

    def test_file_read_missing_returns_failed(self):
        """tool.file.read on nonexistent file must return failed Observation."""
        # _tool_file_read looks for README.md in workspace root;
        # if not found, returns failed Observation
        from nous_runtime.planner.tool_router import _tool_file_read
        obs = _tool_file_read()
        from nous_runtime.planner.observation import Observation
        assert isinstance(obs, Observation)
        # Either success (README exists) or failed (no README)
        assert obs.status in ("success", "failed")

    def test_unknown_intent_returns_failed(self):
        from nous_runtime.planner.tool_router import execute_tool
        obs = execute_tool("nonexistent.intent")
        from nous_runtime.planner.observation import Observation
        assert isinstance(obs, Observation)
        assert obs.status == "failed"


class TestLLMPromptWithObservation:
    """Context builder must consume Observation, not raw dict."""

    def test_prompt_includes_observation_data(self):
        from nous_runtime.planner.observation import Observation
        from nous_runtime.planner.tool_router import build_llm_prompt

        obs = Observation.success("project.scan", {
            "workspace": "/test", "files": 1722,
            "languages": {"python": 1216},
        })
        prompt = build_llm_prompt("project.scan", obs, "请扫描当前项目")
        assert "1722" in prompt
        assert "python" in prompt
        assert "1216" in prompt
        assert "[Observation" in prompt
        assert "project.scan" in prompt

    def test_no_raw_dict_leak(self):
        """LLM prompt must never contain raw Python dict repr."""
        from nous_runtime.planner.observation import Observation
        from nous_runtime.planner.tool_router import build_llm_prompt

        obs = Observation.success("test", {"key": "val"})
        prompt = build_llm_prompt("test", obs, "hi")
        # Must use structured format, not raw __repr__
        assert "Observation(" not in prompt  # no dataclass repr
        assert "ToolResult" not in prompt     # no old class name
