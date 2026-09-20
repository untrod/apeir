"""Persistent model evaluation records used by routing and Model Center."""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.core.events import EventEnvelope
from nous_runtime.model_runtime.errors import ModelRuntimeError
from nous_runtime.model_runtime.models import utc_now


EventSink = Callable[[EventEnvelope], None]


def _bounded(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ModelRuntimeError(f"{name} must be between 0.0 and 1.0")
    return number


@dataclass(frozen=True)
class ModelEvaluation:
    """One outcome observation; it never contains prompts or credentials."""

    model_id: str
    task_type: str
    quality_score: float
    latency_ms: int
    cost_usd: float
    error: bool = False
    evaluation_id: str = field(
        default_factory=lambda: f"modeval_{uuid.uuid4().hex}"
    )
    created_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.model_id).strip():
            raise ModelRuntimeError("model_id is required")
        if not str(self.task_type).strip():
            raise ModelRuntimeError("task_type is required")
        object.__setattr__(
            self, "quality_score", _bounded(self.quality_score, "quality_score")
        )
        if int(self.latency_ms) < 0:
            raise ModelRuntimeError("latency_ms must be non-negative")
        if float(self.cost_usd) < 0 or not math.isfinite(float(self.cost_usd)):
            raise ModelRuntimeError("cost_usd must be non-negative")
        object.__setattr__(self, "latency_ms", int(self.latency_ms))
        object.__setattr__(self, "cost_usd", float(self.cost_usd))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelEvaluation":
        return cls(
            model_id=str(data.get("model_id") or ""),
            task_type=str(data.get("task_type") or ""),
            quality_score=float(data.get("quality_score") or 0.0),
            latency_ms=int(data.get("latency_ms") or 0),
            cost_usd=float(data.get("cost_usd") or 0.0),
            error=bool(data.get("error", False)),
            evaluation_id=str(data.get("evaluation_id") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ModelEvaluationSummary:
    model_id: str
    task_type: str
    sample_count: int
    quality_score: float
    average_latency_ms: float
    average_cost_usd: float
    error_rate: float
    overall_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelEvaluationStore:
    """Thread-safe, optionally persistent evaluation score database."""

    from nous_runtime.schema_registry import MODEL_EVALUATION_SCHEMA_VERSION as _EVAL_VER

    SCHEMA_VERSION = _EVAL_VER

    def __init__(
        self,
        storage_path: str | Path | None = None,
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.event_sink = event_sink
        self._records: list[ModelEvaluation] = []
        self._lock = threading.RLock()
        self._load()

    def record(self, evaluation: ModelEvaluation) -> ModelEvaluation:
        if not isinstance(evaluation, ModelEvaluation):
            raise ModelRuntimeError("evaluation must be a ModelEvaluation")
        with self._lock:
            self._records.append(evaluation)
            self._save_unlocked()
        if self.event_sink is not None:
            self.event_sink(
                EventEnvelope(
                    event_type="model.evaluation.recorded",
                    source="model_evaluation",
                    payload={
                        "evaluation_id": evaluation.evaluation_id,
                        "model_id": evaluation.model_id,
                        "task_type": evaluation.task_type,
                        "quality_score": evaluation.quality_score,
                        "error": evaluation.error,
                    },
                )
            )
        return evaluation

    def list(
        self,
        *,
        model_id: str | None = None,
        task_type: str | None = None,
    ) -> tuple[ModelEvaluation, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._records
                if (model_id is None or item.model_id == model_id)
                and (task_type is None or item.task_type == task_type)
            )

    def summary(
        self,
        model_id: str,
        *,
        task_type: str | None = None,
        latency_reference_ms: float = 10_000.0,
        cost_reference_usd: float = 1.0,
    ) -> ModelEvaluationSummary | None:
        records = self.list(model_id=model_id, task_type=task_type)
        if not records:
            return None
        count = len(records)
        quality = sum(item.quality_score for item in records) / count
        latency = sum(item.latency_ms for item in records) / count
        cost = sum(item.cost_usd for item in records) / count
        error_rate = sum(1 for item in records if item.error) / count
        speed = 1.0 - min(1.0, latency / max(1.0, latency_reference_ms))
        economy = 1.0 - min(1.0, cost / max(0.000001, cost_reference_usd))
        reliability = 1.0 - error_rate
        overall = (
            quality * 0.55
            + speed * 0.15
            + economy * 0.15
            + reliability * 0.15
        )
        return ModelEvaluationSummary(
            model_id=model_id,
            task_type=task_type or "*",
            sample_count=count,
            quality_score=round(quality, 6),
            average_latency_ms=round(latency, 3),
            average_cost_usd=round(cost, 6),
            error_rate=round(error_rate, 6),
            overall_score=round(overall, 6),
        )

    def leaderboard(
        self, *, task_type: str | None = None
    ) -> tuple[ModelEvaluationSummary, ...]:
        model_ids = sorted(
            {
                item.model_id
                for item in self.list(task_type=task_type)
            }
        )
        summaries = [
            summary
            for model_id in model_ids
            if (summary := self.summary(model_id, task_type=task_type))
            is not None
        ]
        return tuple(
            sorted(
                summaries,
                key=lambda item: (-item.overall_score, item.model_id),
            )
        )

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._records = [
                ModelEvaluation.from_dict(item)
                for item in payload.get("records", [])
            ]
        except (OSError, ValueError, TypeError) as exc:
            raise ModelRuntimeError(
                f"failed to load model evaluations: {exc}"
            ) from exc

    def _save_unlocked(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(
            self.storage_path.suffix + ".tmp"
        )
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "records": [item.to_dict() for item in self._records],
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.storage_path)
        except OSError as exc:
            raise ModelRuntimeError(
                f"failed to persist model evaluations: {exc}"
            ) from exc


__all__ = [
    "ModelEvaluation",
    "ModelEvaluationStore",
    "ModelEvaluationSummary",
]
