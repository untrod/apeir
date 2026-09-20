from datetime import datetime, timezone

import pytest

from nous_runtime.retrieval.errors import RetrievalValidationError
from nous_runtime.retrieval.models import (
    AccessScope,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRecord,
    RetrievalResult,
    RetrievalScope,
)
from nous_runtime.retrieval.records.hashing import hash_content


def _record(content: str = "Python project facts") -> RetrievalRecord:
    return RetrievalRecord(
        record_id="retr_1",
        record_type="memory_fact",
        workspace_id="workspace_a",
        project_id="project_a",
        source_id="mem_1",
        source_type="memory",
        title="project.language",
        content=content,
        content_hash=hash_content(content),
        stable_key="project.language",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={"active": True},
        access_scope=AccessScope(workspace_id="workspace_a", project_ids=("project_a",)),
    )


def test_retrieval_record_serializes_and_validates_hash():
    record = _record()
    restored = RetrievalRecord.from_dict(record.to_dict())

    assert restored.record_id == record.record_id
    assert restored.content_hash == hash_content(record.content)
    assert restored.access_scope.workspace_id == "workspace_a"


def test_retrieval_record_rejects_wrong_hash():
    with pytest.raises(RetrievalValidationError):
        RetrievalRecord(
            record_id="retr_bad",
            record_type="memory_fact",
            workspace_id="workspace_a",
            project_id="project_a",
            source_id="mem_bad",
            source_type="memory",
            content="content",
            content_hash="wrong",
            access_scope=AccessScope(workspace_id="workspace_a", project_ids=("project_a",)),
        )


def test_retrieval_query_requires_scope_and_bounded_limit():
    scope = RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",))
    query = RetrievalQuery(text="python", scope=scope, limit=5)

    assert query.mode == "lexical"
    assert query.limit == 5

    with pytest.raises(RetrievalValidationError):
        RetrievalScope(workspace_id="", project_ids=("project_a",))
    with pytest.raises(RetrievalValidationError):
        RetrievalQuery(text="python", scope=scope, limit=0)


def test_filters_reject_unknown_record_types():
    with pytest.raises(RetrievalValidationError):
        RetrievalFilters(record_types=("unknown",))


def test_retrieval_result_is_tool_friendly():
    result = RetrievalResult(
        query_id="rq_1",
        record=_record(),
        score=0.8,
        rank=1,
        matched_text="Python",
        source_backend="local",
        explanation={"token_coverage": 0.7},
    )

    data = result.to_dict()
    assert data["record"]["record_type"] == "memory_fact"
    assert data["explanation"]["token_coverage"] == 0.7
