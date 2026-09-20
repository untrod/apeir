"""Failure collection for long-running Nous soak tests."""

from __future__ import annotations

import traceback
from dataclasses import asdict, dataclass
from time import time


@dataclass(frozen=True)
class FailureRecord:
    timestamp: float
    phase: str
    error_type: str
    message: str
    traceback: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FailureCollector:
    def __init__(self):
        self.records: list[FailureRecord] = []

    def capture(self, phase: str, exc: BaseException) -> None:
        self.records.append(
            FailureRecord(
                timestamp=time(),
                phase=phase,
                error_type=type(exc).__name__,
                message=str(exc),
                traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
        )

    @property
    def count(self) -> int:
        return len(self.records)

    def to_list(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self.records]