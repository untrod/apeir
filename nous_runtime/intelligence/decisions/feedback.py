"""In-memory decision feedback loop foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DecisionFeedback:
    decision_id: str
    input: Mapping[str, Any]
    choice: str
    result: Mapping[str, Any]
    success: bool
    metrics: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "input": dict(self.input),
            "choice": self.choice,
            "result": dict(self.result),
            "success": self.success,
            "metrics": dict(self.metrics),
        }


class DecisionFeedbackStore:
    """Append-only feedback collection; persistence can be added later."""

    def __init__(self) -> None:
        self._records: list[DecisionFeedback] = []

    def record_feedback(self, feedback: DecisionFeedback) -> DecisionFeedback:
        self._records.append(feedback)
        return feedback

    def query_history(
        self,
        *,
        decision_id: str = "",
        success: bool | None = None,
    ) -> list[DecisionFeedback]:
        records = list(self._records)
        if decision_id:
            records = [item for item in records if item.decision_id == decision_id]
        if success is not None:
            records = [item for item in records if item.success is success]
        return records


__all__ = ["DecisionFeedback", "DecisionFeedbackStore"]
