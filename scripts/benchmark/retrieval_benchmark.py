"""Persistent retrieval latency and isolation benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.ranking import pack_context
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry


def _record(index: int, *, project_id: str) -> RetrievalRecord:
    content = f"runtime retrieval record {index} bucket-{index % 100}"
    return RetrievalRecord(
        record_id=f"record-{project_id}-{index:05d}",
        record_type="document_chunk",
        workspace_id="workspace-a",
        project_id=project_id,
        source_id=f"source-{project_id}-{index:05d}",
        source_type="benchmark",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(workspace_id="workspace-a", project_ids=(project_id,)),
    )


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95_index = max(0, int(len(ordered) * 0.95) - 1)
    return {
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(samples), 3),
    }


def run(records: int = 10_000, rounds: int = 30) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / ".nous"
        backend = PersistentLocalRetrievalBackend(workspace)
        project_a_count = max(1, int(records * 0.9))
        values = [
            _record(index, project_id="project-a" if index < project_a_count else "project-b")
            for index in range(records)
        ]
        started = time.perf_counter()
        write = backend.upsert(values, generation_id="benchmark-generation")
        write_ms = (time.perf_counter() - started) * 1000
        registry = RetrievalBackendRegistry()
        registry.register(backend, name="local")
        gateway = RetrievalGateway(backend_registry=registry)
        query = RetrievalQuery(
            text="bucket-42",
            scope=RetrievalScope(workspace_id="workspace-a", project_ids=("project-a",)),
            limit=100,
        )
        samples: list[float] = []
        results = []
        for _ in range(rounds):
            started = time.perf_counter()
            results = gateway.search(query, generation_id="benchmark-generation")
            samples.append((time.perf_counter() - started) * 1000)
        pack_started = time.perf_counter()
        pack = pack_context(results, max_tokens=1200)
        pack_ms = (time.perf_counter() - pack_started) * 1000
        return {
            "benchmark": "retrieval",
            "records": records,
            "rounds": rounds,
            "write_ok": write.ok,
            "bulk_write_ms": round(write_ms, 3),
            "query": _summary(samples),
            "result_count": len(results),
            "scope_isolated": all(item.record.project_id == "project-a" for item in results),
            "context_pack_ms": round(pack_ms, 3),
            "context_tokens": pack.token_estimate,
            "targets": {"query_p95_ms": 100, "context_pack_ms": 25},
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(max(1, args.records), max(1, args.rounds))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
