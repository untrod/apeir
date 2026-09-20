from __future__ import annotations

from nous_runtime.context.builder import ContextBuilder
from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.types import BuildRequest


class StaticProvider:
    def __init__(self, source_type, items):
        self.source_type = source_type
        self.items = items

    def collect(self, request_hint="", limit=100):
        return self.items[:limit]


def test_context_class_budgets_dedup_profile_truncation_and_citations():
    duplicate_memory = ContextItem(
        content="Same   fact",
        source_type="memory",
    )
    duplicate_project = ContextItem(
        content="same fact",
        source_type="project",
    )
    retrieval = ContextItem(
        content="cited knowledge",
        source_type="retrieval",
        source_id="chunk-1",
    )
    long_memory = ContextItem(
        content="x" * 80,
        source_type="memory",
    )
    builder = ContextBuilder(
        providers=[
            StaticProvider(
                "memory",
                [duplicate_memory, long_memory],
            ),
            StaticProvider("project", [duplicate_project]),
            StaticProvider("retrieval", [retrieval]),
        ]
    )

    snapshot = builder.build_context(
        BuildRequest(
            intent="bounded",
            metadata={
                "token_budgets": {
                    "recent_messages": 5,
                    "workspace_facts": 5,
                    "knowledge_retrieval": 10,
                }
            },
        )
    )

    assert snapshot.metadata["duplicate_suppressed"] == 1
    assert snapshot.metadata["truncation_explanation"]
    assert snapshot.metadata["citation_coverage"] == 1.0
    profile = snapshot.metadata["context_build_profile"]
    assert profile["tokens_by_class"]["knowledge_retrieval"] > 0
    assert profile["token_budgets"]["recent_messages"] == 5


def test_context_snapshot_incremental_patch_and_precise_invalidation():
    first = ContextItem(
        item_id="first",
        content="first",
        source_type="memory",
        source_id="source-a",
    )
    second = ContextItem(
        item_id="second",
        content="second",
        source_type="memory",
        source_id="source-b",
    )
    plan = ContextItem(
        item_id="plan",
        content="plan",
        source_type="decision",
        source_id="decision-1",
    )
    base = ContextSnapshot(items=(first, second, plan))
    added = ContextItem(
        item_id="added",
        content="added",
        source_type="retrieval",
        source_id="chunk-2",
    )

    patched = base.apply_patch(
        upsert=(added,),
        invalidate_source_ids=("source-a",),
    )
    invalidated = patched.apply_patch(
        invalidate_source_types=("decision",)
    )

    assert {item.item_id for item in base.items} == {
        "first",
        "second",
        "plan",
    }
    assert {item.item_id for item in patched.items} == {
        "added",
        "second",
        "plan",
    }
    assert {item.item_id for item in invalidated.items} == {
        "added",
        "second",
    }
    assert patched.version == base.version + 1
    assert patched.metadata["base_snapshot_id"] == base.id
    assert patched.metadata["base_checksum"] == base.checksum()
