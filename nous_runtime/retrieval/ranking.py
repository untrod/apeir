"""Ranking and context packing utilities."""

from __future__ import annotations

from dataclasses import dataclass, field

from nous_runtime.retrieval.models import RetrievalResult


@dataclass(frozen=True)
class ContextItem:
    record_id: str
    text: str
    score: float
    source_type: str
    token_estimate: int


@dataclass(frozen=True)
class ContextPack:
    items: tuple[ContextItem, ...]
    text: str
    token_estimate: int
    dropped_record_ids: tuple[str, ...] = field(default_factory=tuple)


def fuse_results(
    result_sets: dict[str, list[RetrievalResult]],
    weights: dict[str, float],
    *,
    limit: int,
) -> list[RetrievalResult]:
    by_record: dict[str, tuple[RetrievalResult, float]] = {}
    for channel, results in result_sets.items():
        weight = weights.get(channel, 1.0)
        for result in results:
            previous = by_record.get(result.record.record_id)
            score = result.score * weight
            if previous is None:
                by_record[result.record.record_id] = (result, score)
            else:
                by_record[result.record.record_id] = (previous[0], previous[1] + score)
    ranked = sorted(by_record.values(), key=lambda item: (-item[1], item[0].rank, item[0].record.record_id))
    fused: list[RetrievalResult] = []
    for rank, (result, score) in enumerate(ranked[:limit], start=1):
        fused.append(
            RetrievalResult(
                query_id=result.query_id,
                record=result.record,
                score=min(1.0, score),
                rank=rank,
                matched_text=result.matched_text,
                source_backend=result.source_backend,
                explanation={**result.explanation, "fused_score": score},
            )
        )
    return fused


def pack_context(results: list[RetrievalResult], *, max_tokens: int = 1200) -> ContextPack:
    items: list[ContextItem] = []
    dropped: list[str] = []
    used = 0
    for result in sorted(results, key=lambda item: (item.rank, -item.score)):
        text = _render_result(result)
        tokens = estimate_tokens(text)
        if used + tokens > max_tokens:
            dropped.append(result.record.record_id)
            continue
        items.append(
            ContextItem(
                record_id=result.record.record_id,
                text=text,
                score=result.score,
                source_type=result.record.source_type,
                token_estimate=tokens,
            )
        )
        used += tokens
    return ContextPack(
        items=tuple(items),
        text="\n\n".join(item.text for item in items),
        token_estimate=used,
        dropped_record_ids=tuple(dropped),
    )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _render_result(result: RetrievalResult) -> str:
    title = result.record.title or result.record.record_type
    return f"[{result.rank}] {title}\n{result.record.content}"
