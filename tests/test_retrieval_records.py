from nous_runtime.retrieval.records.mapper import map_memory_records, memory_record_to_retrieval


def test_memory_fact_maps_to_canonical_retrieval_record():
    record = {
        "memory_id": "mem_1",
        "record_type": "fact",
        "project_id": "project_a",
        "source_type": "runtime",
        "key": "project.language",
        "value": "python",
        "stable_key": "project.language",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"source": "scan"},
    }

    mapped = memory_record_to_retrieval(record, workspace_id="workspace_a")

    assert mapped.record_type == "memory_fact"
    assert mapped.workspace_id == "workspace_a"
    assert mapped.project_id == "project_a"
    assert mapped.source_id == "mem_1"
    assert mapped.stable_key == "project.language"
    assert mapped.content == "project.language: python"
    assert mapped.metadata["source"] == "scan"
    assert mapped.active is True


def test_memory_records_map_deterministically():
    record = {
        "memory_id": "mem_1",
        "record_type": "event",
        "project_id": "project_a",
        "event_type": "task_completed",
        "detail": "Task completed",
    }

    first = map_memory_records([record], "workspace_a")[0]
    second = map_memory_records([record], "workspace_a")[0]

    assert first.record_id == second.record_id
    assert first.record_type == "memory_event"


def test_memory_mapper_preserves_supersedes_for_derived_indexing():
    record = {
        "memory_id": "mem_2",
        "record_type": "fact",
        "project_id": "project_a",
        "key": "project.files.total",
        "value": 12,
        "supersedes": "mem_1",
    }

    mapped = memory_record_to_retrieval(record, workspace_id="workspace_a")

    assert mapped.supersedes == "mem_1"
    assert mapped.metadata["active"] is True
