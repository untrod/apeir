# -*- coding: utf-8 -*-
"""Structured project memory engine tests."""

import json
from pathlib import Path


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    (ws / "memory").mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"name": "test_project"}), encoding="utf-8")
    return ws


class TestMemoryRecords:
    def test_memory_event_serializes(self):
        from nous_runtime.project.memory_records import MemoryEvent

        event = MemoryEvent(
            source_type="observation",
            project_id="proj",
            event_type="task_completed",
            detail="Task completed",
        )
        data = event.to_dict()

        assert data["schema_version"] == "1.0"
        assert data["record_type"] == "event"
        assert data["memory_id"]
        assert event.validate() == []


class TestMemoryStorage:
    def test_fact_supersession_and_active_facts(self, tmp_path):
        from nous_runtime.project.memory import add_fact, active_facts, read_all

        ws = _workspace(tmp_path)
        first = add_fact(ws, "project.files.total", 10, "scan")
        second = add_fact(ws, "project.files.total", 12, "scan")

        facts = read_all(ws, "facts")
        active = active_facts(ws)

        assert len(facts) == 2
        assert second["supersedes"] == first["memory_id"]
        assert len(active) == 1
        assert active[0]["value"] == 12

    def test_malformed_jsonl_recovery(self, tmp_path):
        from nous_runtime.project.memory import read_all

        ws = _workspace(tmp_path)
        fp = Path(ws) / "memory" / "events.jsonl"
        fp.write_text('{"ok": true}\nnot-json\n{"ok": false}\n', encoding="utf-8")

        records = read_all(ws, "events")

        assert len(records) == 2

    def test_secret_redaction(self, tmp_path):
        from nous_runtime.project.memory import add_memory_record
        from nous_runtime.project.memory_records import MemoryEvent

        ws = _workspace(tmp_path)
        record = MemoryEvent(
            source_type="runtime",
            event_type="secret_test",
            detail="safe",
            metadata={"api_key": "real-key", "normal": "ok"},
        )

        saved = add_memory_record(ws, record)

        assert saved["metadata"]["api_key"] == "<redacted>"
        assert saved["metadata"]["normal"] == "ok"


class TestMemoryIngestor:
    def test_project_scan_observation_creates_event_and_facts(self, tmp_path):
        from nous_runtime.planner.observation import Observation
        from nous_runtime.project.memory import read_all, active_facts
        from nous_runtime.project.memory_ingestor import MemoryIngestor

        ws = _workspace(tmp_path)
        obs = Observation.success(
            "project.scan",
            {
                "files": 42,
                "total_size_kb": 12.5,
                "languages": {"python": 10},
            },
        )

        persisted = MemoryIngestor(ws).ingest(obs)

        assert persisted
        assert any(r["record_type"] == "event" for r in persisted)
        facts = active_facts(ws)
        assert any(f["key"] == "project.files.total" and f["value"] == 42 for f in facts)
        assert read_all(ws, "events")

    def test_task_observation_creates_task_event_and_summary(self, tmp_path):
        from nous_runtime.planner.observation import Observation
        from nous_runtime.project.memory import read_all
        from nous_runtime.project.memory_ingestor import MemoryIngestor

        ws = _workspace(tmp_path)
        obs = Observation.success(
            "task.execute",
            {"task_id": "task_1", "capability_id": "model.reason", "result": {"ok": True, "content": "large raw response"}},
            capability="model.reason",
            metadata={"task_id": "task_1", "provider_id": "openai"},
        )

        MemoryIngestor(ws).ingest(obs)

        events = read_all(ws, "events")
        summaries = read_all(ws, "summaries")
        assert any(e["task_id"] == "task_1" for e in events)
        assert summaries
        assert "large raw response" not in summaries[-1]["content"]

    def test_failed_provider_observation_creates_experience(self, tmp_path):
        from nous_runtime.planner.observation import Observation
        from nous_runtime.project.memory import experience_for
        from nous_runtime.project.memory_ingestor import MemoryIngestor

        ws = _workspace(tmp_path)
        obs = Observation.failure(
            "provider.invoke",
            ["timeout"],
            capability="model.reason",
            metadata={"provider_id": "openai", "error_code": "TIMEOUT"},
        )

        MemoryIngestor(ws).ingest(obs)

        experiences = experience_for(ws, "model.reason")
        assert len(experiences) == 1
        assert experiences[0]["outcome"] == "failed"
        assert experiences[0]["error_code"] == "TIMEOUT"


class TestMemoryRetrieval:
    def test_search_and_context_budget(self, tmp_path):
        from nous_runtime.project.memory import add_fact, search_memory
        from nous_runtime.project.memory_context import build_memory_context

        ws = _workspace(tmp_path)
        add_fact(ws, "project.language.python.files", 10, "scan")

        results = search_memory(ws, "python")
        context = build_memory_context(ws, query="python", max_records=2, max_characters=500)

        assert results
        assert context["record_count"] <= 2
        assert context["characters"] <= 500
        assert "python" in context["context"]
