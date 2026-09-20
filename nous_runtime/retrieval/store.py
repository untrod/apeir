"""JSONL metadata store for retrieval index generations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from nous_runtime.retrieval.indexing import IndexGeneration, IndexGenerationState


class IndexGenerationStore(Protocol):
    def append(self, generation: IndexGeneration) -> None:
        ...

    def get(self, generation_id: str) -> IndexGeneration | None:
        ...

    def list(self, logical_index: str | None = None) -> list[IndexGeneration]:
        ...

    def active(self, logical_index: str, workspace_id: str, project_id: str) -> IndexGeneration | None:
        ...

    def update_state(
        self,
        generation_id: str,
        state: IndexGenerationState,
        *,
        failure_reason: str | None = None,
        verified: bool | None = None,
    ) -> IndexGeneration:
        ...


class JsonlIndexGenerationStore:
    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path)
        self.root = self.workspace_path / "retrieval"
        self.generations_path = self.root / "index_generations.jsonl"
        self.events_path = self.root / "index_events.jsonl"

    def append(self, generation: IndexGeneration) -> None:
        self._append_jsonl(self.generations_path, generation.to_dict())
        self.append_event(generation.generation_id, "generation_snapshot", generation.to_dict())

    def get(self, generation_id: str) -> IndexGeneration | None:
        return _latest_by_id(self.list()).get(generation_id)

    def list(self, logical_index: str | None = None) -> list[IndexGeneration]:
        latest = _latest_by_id(_read_generations(self.generations_path))
        generations = list(latest.values())
        if logical_index:
            generations = [g for g in generations if g.logical_index == logical_index]
        return sorted(generations, key=lambda g: g.created_at)

    def active(self, logical_index: str, workspace_id: str, project_id: str) -> IndexGeneration | None:
        matches = [
            g for g in self.list(logical_index)
            if g.workspace_id == workspace_id
            and g.project_id == project_id
            and g.state == IndexGenerationState.ACTIVE
        ]
        return matches[-1] if matches else None

    def update(self, generation: IndexGeneration) -> None:
        self.append(generation)

    def update_state(
        self,
        generation_id: str,
        state: IndexGenerationState,
        *,
        failure_reason: str | None = None,
        verified: bool | None = None,
    ) -> IndexGeneration:
        generation = self.get(generation_id)
        if generation is None:
            raise KeyError(f"generation not found: {generation_id}")
        updated = generation.with_state(state, failure_reason=failure_reason, verified=verified)
        self.append(updated)
        return updated

    def append_event(self, generation_id: str, event_type: str, payload: dict) -> None:
        self._append_jsonl(
            self.events_path,
            {
                "generation_id": generation_id,
                "event_type": event_type,
                "payload": payload,
            },
        )

    def _append_jsonl(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def _read_generations(path: Path) -> list[IndexGeneration]:
    if not path.is_file():
        return []
    generations: list[IndexGeneration] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                generations.append(IndexGeneration.from_dict(data))
    return generations


def _latest_by_id(generations: list[IndexGeneration]) -> dict[str, IndexGeneration]:
    latest: dict[str, IndexGeneration] = {}
    for generation in generations:
        latest[generation.generation_id] = generation
    return latest
