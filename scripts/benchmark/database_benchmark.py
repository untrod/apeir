"""SQLite persistence benchmark for Context and Experience stores."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.store import ContextStore
from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.schema import ExperienceSource
from nous_runtime.experience.store import ExperienceStore


def _time_ms(fn: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = fn()
    return (time.perf_counter() - start) * 1000, result


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "mean_ms": round(statistics.mean(samples), 3) if samples else 0.0,
        "median_ms": round(statistics.median(samples), 3) if samples else 0.0,
        "p95_ms": round(ordered[int(len(ordered) * 0.95) - 1], 3) if len(ordered) >= 20 else round(ordered[-1], 3) if ordered else 0.0,
        "max_ms": round(max(samples), 3) if samples else 0.0,
    }


def _context_snapshot(i: int) -> ContextSnapshot:
    item = ContextItem(
        item_id=f"ctx_item_{i:05d}",
        content=f"runtime context benchmark item {i} search-key-{i % 10}",
        source_type=ContextSource.RUNTIME.value,
        source_id=f"source_{i:05d}",
        importance=(i % 10) / 10,
        confidence=0.8,
        permission="read",
        tags=("benchmark", f"bucket-{i % 10}"),
    )
    return ContextSnapshot(
        id=f"snap_{i:05d}",
        items=(item,),
        sources=(ContextSource.RUNTIME.value,),
        confidence=0.8,
        runtime={"benchmark": True, "index": i},
    )


def _experience_record(i: int) -> ExperienceRecord:
    return ExperienceRecord(
        id=f"exp_{i:05d}",
        source_type=ExperienceSource.SYSTEM.value,
        task_type="benchmark" if i % 2 else "runtime",
        task_summary=f"benchmark runtime operation {i} search-key-{i % 10}",
        context_hash=f"hash_{i % 100}",
        action="measure sqlite persistence",
        agent_id="benchmark.agent",
        provider_id="benchmark.provider",
        capability_id="benchmark.capability",
        result="success" if i % 5 else "partial",
        evaluation_score=0.8,
        success=i % 5 != 0,
        lessons=("measure before optimizing",),
        confidence=0.8,
    )


def run(records: int = 10_000) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td) / ".nous"
        context_store = ContextStore(workspace)
        experience_store = ExperienceStore(workspace)

        context_writes: list[float] = []
        experience_writes: list[float] = []

        for i in range(records):
            d, _ = _time_ms(lambda i=i: context_store.save(_context_snapshot(i)))
            context_writes.append(d)
        for i in range(records):
            d, _ = _time_ms(lambda i=i: experience_store.save(_experience_record(i)))
            experience_writes.append(d)

        context_get_ms, got = _time_ms(lambda: context_store.get(f"snap_{records // 2:05d}"))
        context_list_ms, listed = _time_ms(lambda: context_store.list(limit=100))
        context_restore_ms, restored = _time_ms(lambda: context_store.restore(f"snap_{records // 3:05d}"))
        experience_search_ms, found = _time_ms(lambda: experience_store.search("search-key-5", limit=100))
        experience_list_ms, exp_list = _time_ms(lambda: experience_store.list(task_type="runtime", limit=100))
        experience_stats_ms, stats = _time_ms(lambda: experience_store.stats())

        return {
            "benchmark": "database",
            "records": records,
            "targets": {"query_ms": 100, "restore_ms": 1000, "write_ms": 50},
            "context": {
                "write": _summary(context_writes),
                "get_ms": round(context_get_ms, 3),
                "list_100_ms": round(context_list_ms, 3),
                "restore_ms": round(context_restore_ms, 3),
                "get_ok": got is not None,
                "restore_ok": restored is not None,
                "listed": len(listed),
            },
            "experience": {
                "write": _summary(experience_writes),
                "search_100_ms": round(experience_search_ms, 3),
                "list_100_ms": round(experience_list_ms, 3),
                "stats_ms": round(experience_stats_ms, 3),
                "found": len(found),
                "listed": len(exp_list),
                "stats": stats,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(max(1, args.records))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()