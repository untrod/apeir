# -*- coding: utf-8 -*-
"""Project workspace tests — .nous/ detection and creation."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestFindWorkspace:
    def test_no_workspace_returns_none(self, tmp_path, monkeypatch):
        import nous_runtime.project.workspace as workspace_module

        marker = f".nous-test-missing-{tmp_path.name}"
        monkeypatch.setattr(workspace_module, "NOUS_DIR", marker)
        assert workspace_module.find_workspace(tmp_path) is None

    def test_finds_workspace_at_current_dir(self, tmp_path):
        (tmp_path / ".nous").mkdir()
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace(tmp_path)
        assert ws is not None
        assert ws.name == ".nous"

    def test_finds_workspace_from_nested_dir(self, tmp_path):
        (tmp_path / ".nous").mkdir()
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace(nested)
        assert ws is not None
        assert ws == tmp_path / ".nous"

    def test_finds_nearest_workspace(self, tmp_path):
        (tmp_path / ".nous").mkdir()
        deeper = tmp_path / "sub"
        deeper.mkdir()
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace(deeper)
        assert ws == tmp_path / ".nous"

    def test_configured_workspace_does_not_fall_back_to_parent(self, tmp_path, monkeypatch):
        from nous_runtime.project.workspace import find_workspace

        selected = tmp_path / "selected"
        selected.mkdir()
        (tmp_path / ".nous").mkdir()
        monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(selected))

        assert find_workspace() is None


class TestInitWorkspace:
    def test_init_uses_configured_workspace_root(self, tmp_path, monkeypatch):
        from nous_runtime.project.workspace import init_workspace

        selected = tmp_path / "selected"
        monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(selected))

        assert init_workspace() == selected / ".nous"

    def test_init_creates_structure(self, tmp_path):
        from nous_runtime.project.workspace import init_workspace

        ws = init_workspace(tmp_path)
        assert ws.is_dir()
        assert ws.name == ".nous"

        # Required directories
        assert (ws / "memory").is_dir()
        assert (ws / "index").is_dir()
        assert (ws / "traces").is_dir()
        assert (ws / "artifacts").is_dir()

        # Required files
        assert (ws / "project.json").is_file()
        assert (ws / "config.json").is_file()
        assert (ws / "goals.json").is_file()
        assert (ws / "tasks.json").is_file()
        assert (ws / "history").is_file()

        # Memory placeholders
        assert (ws / "memory" / "timeline.jsonl").is_file()
        assert (ws / "memory" / "decisions.jsonl").is_file()
        assert (ws / "memory" / "summaries.jsonl").is_file()
        assert (ws / "memory" / "facts.jsonl").is_file()

        # Index placeholder
        assert (ws / "index" / "files.json").is_file()

    def test_project_json_content(self, tmp_path):
        from nous_runtime.project.workspace import init_workspace
        import json

        ws = init_workspace(tmp_path)
        data = json.loads((ws / "project.json").read_text(encoding="utf-8"))
        assert "name" in data
        assert "root" in data
        assert "created" in data

    def test_double_init_is_safe(self, tmp_path):
        from nous_runtime.project.workspace import init_workspace

        ws1 = init_workspace(tmp_path)
        ws2 = init_workspace(tmp_path)
        assert ws1 == ws2
        # project.json should NOT be overwritten
        import json
        data = json.loads((ws1 / "project.json").read_text(encoding="utf-8"))
        assert "name" in data

    def test_timeline_event_on_create(self, tmp_path):
        from nous_runtime.project.workspace import init_workspace
        from nous_runtime.project.memory import read_recent

        ws = init_workspace(tmp_path)
        events = read_recent(str(ws), "timeline")
        assert len(events) >= 1
        assert events[0]["type"] == "workspace_created"
