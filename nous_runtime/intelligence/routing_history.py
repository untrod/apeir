"""Small JSONL-compatible decision history for explainable routing."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class RoutingDecisionHistory:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def record(self, decision: Any) -> None:
        payload = decision.to_dict()
        decision_id = str(payload.get("decision_id") or "")
        if not decision_id:
            return
        with self._lock:
            self._records[decision_id] = payload
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        + "\n"
                    )

    def get_payload(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock:
            if decision_id in self._records:
                return dict(self._records[decision_id])
        if self.path is None or not self.path.is_file():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("decision_id") == decision_id:
                return payload
        return None

    def list_payloads(self) -> list[dict[str, Any]]:
        if self.path is not None and self.path.is_file():
            records: dict[str, dict[str, Any]] = {}
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                decision_id = str(payload.get("decision_id") or "")
                if decision_id:
                    records[decision_id] = payload
            return list(records.values())
        with self._lock:
            return list(self._records.values())


DEFAULT_ROUTING_HISTORY = RoutingDecisionHistory()


__all__ = ["DEFAULT_ROUTING_HISTORY", "RoutingDecisionHistory"]
