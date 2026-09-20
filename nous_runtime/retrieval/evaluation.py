"""Retrieval evaluation primitives."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import RetrievalQuery


@dataclass(frozen=True)
class RetrievalEvalCase:
    name: str
    query: RetrievalQuery
    expected_record_ids: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalEvalResult:
    name: str
    passed: bool
    returned_record_ids: tuple[str, ...]
    expected_record_ids: tuple[str, ...]
    precision_at_k: float
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RetrievalEvalReport:
    results: tuple[RetrievalEvalResult, ...]
    recall_at_1: float
    recall_at_5: float
    mrr: float
    ndcg_at_5: float
    latency_p50_ms: float
    latency_p95_ms: float


def evaluate_cases(gateway: RetrievalGateway, cases: list[RetrievalEvalCase]) -> list[RetrievalEvalResult]:
    return list(evaluate_report(gateway, cases).results)


def evaluate_report(gateway: RetrievalGateway, cases: list[RetrievalEvalCase]) -> RetrievalEvalReport:
    results: list[RetrievalEvalResult] = []
    for case in cases:
        started = time.perf_counter()
        retrieved = gateway.search(case.query)
        latency_ms = (time.perf_counter() - started) * 1000
        returned = tuple(result.record.record_id for result in retrieved)
        expected = set(case.expected_record_ids)
        hits = sum(1 for record_id in returned if record_id in expected)
        precision = hits / len(returned) if returned else 0.0
        recall_at_1 = _recall(returned[:1], expected)
        recall_at_5 = _recall(returned[:5], expected)
        mrr = _mrr(returned, expected)
        ndcg = _ndcg(returned[:5], expected)
        results.append(
            RetrievalEvalResult(
                name=case.name,
                passed=expected.issubset(set(returned)),
                returned_record_ids=returned,
                expected_record_ids=case.expected_record_ids,
                precision_at_k=precision,
                recall_at_1=recall_at_1,
                recall_at_5=recall_at_5,
                mrr=mrr,
                ndcg_at_5=ndcg,
                latency_ms=latency_ms,
            )
        )
    latencies = sorted(result.latency_ms for result in results)
    return RetrievalEvalReport(
        results=tuple(results),
        recall_at_1=_avg([r.recall_at_1 for r in results]),
        recall_at_5=_avg([r.recall_at_5 for r in results]),
        mrr=_avg([r.mrr for r in results]),
        ndcg_at_5=_avg([r.ndcg_at_5 for r in results]),
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
    )


def _recall(returned: tuple[str, ...], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(set(returned).intersection(expected)) / len(expected)


def _mrr(returned: tuple[str, ...], expected: set[str]) -> float:
    for idx, record_id in enumerate(returned, start=1):
        if record_id in expected:
            return 1.0 / idx
    return 0.0


def _ndcg(returned: tuple[str, ...], expected: set[str]) -> float:
    if not expected:
        return 1.0
    dcg = 0.0
    for idx, record_id in enumerate(returned, start=1):
        if record_id in expected:
            dcg += 1.0 / math.log2(idx + 1)
    ideal_hits = min(len(expected), len(returned))
    ideal = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return values[idx]
