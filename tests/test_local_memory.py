# -*- coding: utf-8 -*-
"""Local memory tests — JSONL append and read."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def workspace(tmp_path):
    d = tmp_path / ".nous"
    d.mkdir()
    (d / "memory").mkdir()
    return str(d)


class TestAddEvent:
    def test_add_event_writes_jsonl(self, workspace):
        from nous_runtime.project.memory import add_event
        entry = add_event(workspace, "test_event", "test detail")
        assert "id" in entry
        assert entry["type"] == "test_event"

        fp = Path(workspace) / "memory" / "timeline.jsonl"
        lines = fp.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "test_event"


class TestReadRecent:
    def test_read_recent_returns_entries(self, workspace):
        from nous_runtime.project.memory import add_event, read_recent

        for i in range(5):
            add_event(workspace, "event", f"detail {i}")

        entries = read_recent(workspace, "timeline", limit=3)
        assert len(entries) == 3
        # Most recent first in the returned list
        assert entries[-1]["detail"] == "detail 4"

    def test_empty_memory_read_returns_empty(self, workspace):
        from nous_runtime.project.memory import read_recent
        entries = read_recent(workspace, "timeline")
        assert entries == []


class TestAddDecision:
    def test_add_decision_structure(self, workspace):
        from nous_runtime.project.memory import add_decision
        entry = add_decision(workspace, "Use what?", "SQLite", "It works")
        assert entry["question"] == "Use what?"
        assert entry["answer"] == "SQLite"

        fp = Path(workspace) / "memory" / "decisions.jsonl"
        assert fp.is_file()
        data = json.loads(fp.read_text(encoding="utf-8").strip())
        assert data["rationale"] == "It works"


class TestAddFact:
    def test_add_fact_structure(self, workspace):
        from nous_runtime.project.memory import add_fact
        entry = add_fact(workspace, "author", "kicoyini45", "git config")
        assert entry["key"] == "author"
        assert entry["value"] == "kicoyini45"

        fp = Path(workspace) / "memory" / "facts.jsonl"
        assert fp.is_file()


class TestAddSummary:
    def test_add_summary_structure(self, workspace):
        from nous_runtime.project.memory import add_summary
        entry = add_summary(
            workspace, "Phase 1 complete", tags=["milestone", "v1.1"]
        )
        assert entry["content"] == "Phase 1 complete"
        assert entry["tags"] == ["milestone", "v1.1"]


class TestReadAll:
    def test_read_all_timeline(self, workspace):
        from nous_runtime.project.memory import add_event, read_all

        for i in range(3):
            add_event(workspace, "event", f"detail {i}")

        all_events = read_all(workspace, "timeline")
        assert len(all_events) == 3

    def test_read_all_empty_file(self, workspace):
        from nous_runtime.project.memory import read_all
        # Empty workspace — no file exists yet
        entries = read_all(workspace, "decisions")
        assert entries == []
