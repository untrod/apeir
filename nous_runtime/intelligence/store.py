"""Decision lifecycle store implementations."""

from __future__ import annotations

import json
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from nous_runtime.locking import file_lock
from nous_runtime.intelligence.models import (
    ExecutionOutcome,
    LifecycleTransition,
    OutcomeAssessment,
    OutcomeFeedback,
    RuntimeDecision,
)


class DecisionStore(Protocol):
    def append_lifecycle_event(self, event: LifecycleTransition) -> bool:
        ...

    def persist_decision_snapshot(self, decision: RuntimeDecision) -> bool:
        ...

    def persist_outcome(self, outcome: ExecutionOutcome) -> bool:
        ...

    def persist_assessment(self, assessment: OutcomeAssessment) -> bool:
        ...

    def persist_feedback(self, feedback: OutcomeFeedback) -> bool:
        ...

    def read_decision(self, decision_id: str) -> RuntimeDecision | None:
        ...

    def read_outcome(self, outcome_id: str) -> ExecutionOutcome | None:
        ...

    def read_timeline(self, decision_id: str) -> list[LifecycleTransition]:
        ...

    def list_decisions(self, limit: int = 50) -> list[RuntimeDecision]:
        ...

    def list_outcomes(self, limit: int = 50, decision_id: str = "") -> list[ExecutionOutcome]:
        ...

    def find_incomplete_decisions(self) -> list[RuntimeDecision]:
        ...

    def verify_integrity(self) -> dict[str, Any]:
        ...

    def rebuild_indexes(self) -> dict[str, Any]:
        ...

    def compact(self, *, dry_run: bool = True) -> dict[str, Any]:
        ...

    def stats(self) -> dict[str, Any]:
        ...


@dataclass
class InMemoryDecisionStore:
    events: dict[str, LifecycleTransition] = field(default_factory=dict)
    decisions: dict[str, RuntimeDecision] = field(default_factory=dict)
    outcomes: dict[str, ExecutionOutcome] = field(default_factory=dict)
    assessments: dict[str, OutcomeAssessment] = field(default_factory=dict)
    feedback: dict[str, OutcomeFeedback] = field(default_factory=dict)

    def append_lifecycle_event(self, event: LifecycleTransition) -> bool:
        if event.event_id in self.events:
            return False
        self.events[event.event_id] = event
        return True

    def persist_decision_snapshot(self, decision: RuntimeDecision) -> bool:
        if decision.decision_id in self.decisions:
            return False
        self.decisions[decision.decision_id] = decision
        return True

    def persist_outcome(self, outcome: ExecutionOutcome) -> bool:
        if outcome.outcome_id in self.outcomes:
            return False
        self.outcomes[outcome.outcome_id] = outcome
        return True

    def persist_assessment(self, assessment: OutcomeAssessment) -> bool:
        if assessment.assessment_id in self.assessments:
            return False
        self.assessments[assessment.assessment_id] = assessment
        return True

    def persist_feedback(self, feedback: OutcomeFeedback) -> bool:
        if feedback.feedback_id in self.feedback:
            return False
        self.feedback[feedback.feedback_id] = feedback
        return True

    def read_decision(self, decision_id: str) -> RuntimeDecision | None:
        return self.decisions.get(decision_id)

    def read_outcome(self, outcome_id: str) -> ExecutionOutcome | None:
        return self.outcomes.get(outcome_id)

    def read_timeline(self, decision_id: str) -> list[LifecycleTransition]:
        return sorted((e for e in self.events.values() if e.decision_id == decision_id), key=lambda e: e.timestamp)

    def list_decisions(self, limit: int = 50) -> list[RuntimeDecision]:
        return list(self.decisions.values())[-limit:]

    def list_outcomes(self, limit: int = 50, decision_id: str = "") -> list[ExecutionOutcome]:
        rows = [o for o in self.outcomes.values() if not decision_id or o.decision_id == decision_id]
        return rows[-limit:]

    def find_incomplete_decisions(self) -> list[RuntimeDecision]:
        return [decision for decision in self.decisions.values() if _latest_status(self.read_timeline(decision.decision_id)) != "closed"]

    def verify_integrity(self) -> dict[str, Any]:
        return {"ok": True, "invalid_records": 0, "duplicates": 0}

    def rebuild_indexes(self) -> dict[str, Any]:
        return {"ok": True, "decisions": len(self.decisions), "outcomes": len(self.outcomes)}

    def compact(self, *, dry_run: bool = True) -> dict[str, Any]:
        return {"ok": True, "dry_run": dry_run, "would_rewrite": 0}

    def stats(self) -> dict[str, Any]:
        return {
            "events": len(self.events),
            "decisions": len(self.decisions),
            "outcomes": len(self.outcomes),
            "assessments": len(self.assessments),
            "feedback": len(self.feedback),
        }


class JsonlDecisionStore:
    SUPPORTED_CONCURRENCY_MODES = {"single_process", "file_lock"}

    def __init__(self, workspace_path: str | Path, *, concurrency_mode: str = "single_process"):
        if concurrency_mode not in self.SUPPORTED_CONCURRENCY_MODES:
            valid = ", ".join(sorted(self.SUPPORTED_CONCURRENCY_MODES))
            raise ValueError(f"unsupported decision store concurrency mode: {concurrency_mode}; expected one of: {valid}")
        self.concurrency_mode = concurrency_mode
        self.root = Path(workspace_path) / "intelligence"
        self.index_root = self.root / "indexes"
        self.manifest_root = self.root / "manifests"
        self.manifest_path = self.manifest_root / "store.json"
        self.lock_path = self.root / ".store.lock"
        self._lock = threading.RLock()
        self.events_path = self.root / "events.jsonl"
        self.snapshots_path = self.root / "snapshots.jsonl"
        self.outcomes_path = self.root / "outcomes.jsonl"
        self.assessments_path = self.root / "assessments.jsonl"
        self.feedback_path = self.root / "feedback.jsonl"
        self.metrics_path = self.root / "metrics.jsonl"
        self._write_manifest()

    def append_lifecycle_event(self, event: LifecycleTransition) -> bool:
        return self._append_unique(self.events_path, "event_id", event.event_id, event.to_dict())

    def persist_decision_snapshot(self, decision: RuntimeDecision) -> bool:
        return self._append_unique(self.snapshots_path, "decision_id", decision.decision_id, decision.to_dict())

    def persist_outcome(self, outcome: ExecutionOutcome) -> bool:
        return self._append_unique(self.outcomes_path, "outcome_id", outcome.outcome_id, outcome.to_dict())

    def persist_assessment(self, assessment: OutcomeAssessment) -> bool:
        return self._append_unique(self.assessments_path, "assessment_id", assessment.assessment_id, assessment.to_dict())

    def persist_feedback(self, feedback: OutcomeFeedback) -> bool:
        return self._append_unique(self.feedback_path, "feedback_id", feedback.feedback_id, feedback.to_dict())

    def read_decision(self, decision_id: str) -> RuntimeDecision | None:
        for row in reversed(_read_jsonl(self.snapshots_path)["records"]):
            if row.get("decision_id") == decision_id:
                return RuntimeDecision.from_dict(row)
        return None

    def read_outcome(self, outcome_id: str) -> ExecutionOutcome | None:
        for row in reversed(_read_jsonl(self.outcomes_path)["records"]):
            if row.get("outcome_id") == outcome_id:
                return ExecutionOutcome.from_dict(row)
        return None

    def read_timeline(self, decision_id: str) -> list[LifecycleTransition]:
        events = [
            LifecycleTransition.from_dict(row)
            for row in _read_jsonl(self.events_path)["records"]
            if row.get("decision_id") == decision_id
        ]
        return sorted(events, key=lambda event: event.timestamp)

    def list_decisions(self, limit: int = 50) -> list[RuntimeDecision]:
        return [RuntimeDecision.from_dict(row) for row in _read_jsonl(self.snapshots_path)["records"]][-limit:]

    def list_outcomes(self, limit: int = 50, decision_id: str = "") -> list[ExecutionOutcome]:
        rows = [
            ExecutionOutcome.from_dict(row)
            for row in _read_jsonl(self.outcomes_path)["records"]
            if not decision_id or row.get("decision_id") == decision_id
        ]
        return rows[-limit:]

    def find_incomplete_decisions(self) -> list[RuntimeDecision]:
        decisions = self.list_decisions(limit=10000)
        events_by_decision: dict[str, list[LifecycleTransition]] = {}
        for row in _read_jsonl(self.events_path)["records"]:
            decision_id = str(row.get("decision_id") or "")
            if not decision_id:
                continue
            events_by_decision.setdefault(decision_id, []).append(
                LifecycleTransition.from_dict(row)
            )

        terminal = {"closed", "cancelled", "superseded"}
        incomplete: list[RuntimeDecision] = []
        for decision in decisions:
            timeline = sorted(
                events_by_decision.get(decision.decision_id, ()),
                key=lambda event: event.timestamp,
            )
            if _latest_status(timeline) not in terminal:
                incomplete.append(decision)
        return incomplete

    def verify_integrity(self) -> dict[str, Any]:
        files = {
            "events": _read_jsonl(self.events_path),
            "snapshots": _read_jsonl(self.snapshots_path),
            "outcomes": _read_jsonl(self.outcomes_path),
            "assessments": _read_jsonl(self.assessments_path),
            "feedback": _read_jsonl(self.feedback_path),
        }
        invalid = sum(len(item["invalid"]) for item in files.values())
        duplicates = sum(_duplicate_count(item["records"]) for item in files.values())
        concurrency = self.concurrency_diagnostic()
        return {
            "ok": invalid == 0 and duplicates == 0 and not concurrency["unsafe"],
            "invalid_records": invalid,
            "duplicates": duplicates,
            "files": list(files),
            "concurrency": concurrency,
        }

    def rebuild_indexes(self) -> dict[str, Any]:
        with self._concurrency_guard():
            self.index_root.mkdir(parents=True, exist_ok=True)
            decision_ids = [decision.decision_id for decision in self.list_decisions(limit=10000)]
            outcome_ids = [outcome.outcome_id for outcome in self.list_outcomes(limit=10000)]
            (self.index_root / "decision_ids.json").write_text(json.dumps(decision_ids, indent=2), encoding="utf-8")
            (self.index_root / "outcome_ids.json").write_text(json.dumps(outcome_ids, indent=2), encoding="utf-8")
            return {"ok": True, "decisions": len(decision_ids), "outcomes": len(outcome_ids)}

    def compact(self, *, dry_run: bool = True) -> dict[str, Any]:
        stats = self.stats()
        return {"ok": True, "dry_run": dry_run, "would_rewrite": sum(stats.values())}

    def stats(self) -> dict[str, Any]:
        return {
            "events": len(_read_jsonl(self.events_path)["records"]),
            "decisions": len(_read_jsonl(self.snapshots_path)["records"]),
            "outcomes": len(_read_jsonl(self.outcomes_path)["records"]),
            "assessments": len(_read_jsonl(self.assessments_path)["records"]),
            "feedback": len(_read_jsonl(self.feedback_path)["records"]),
        }

    def concurrency_diagnostic(self) -> dict[str, Any]:
        manifest = _read_json_object(self.manifest_path)
        manifest_mode = str(manifest.get("concurrency_mode") or "")
        unsafe = False
        warnings: list[str] = []
        if manifest_mode and manifest_mode != self.concurrency_mode:
            unsafe = True
            warnings.append("CONCURRENCY_MODE_MISMATCH")
        if self.concurrency_mode == "single_process":
            warnings.append("SINGLE_PROCESS_MODE_NOT_MULTI_PROCESS_SAFE")
        return {
            "mode": self.concurrency_mode,
            "manifest_mode": manifest_mode or self.concurrency_mode,
            "unsafe": unsafe,
            "warnings": warnings,
        }

    def _append_unique(self, path: Path, key: str, value: str, data: dict[str, Any]) -> bool:
        with self._concurrency_guard():
            if any(row.get(key) == value for row in _read_jsonl(path)["records"]):
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
            return True

    @contextmanager
    def _concurrency_guard(self) -> Iterator[None]:
        with self._lock:
            if self.concurrency_mode == "single_process":
                yield
                return
            if self.concurrency_mode == "file_lock":
                with file_lock(self.lock_path):
                    yield
                return
            raise ValueError(f"unsupported decision store concurrency mode: {self.concurrency_mode}")

    def _write_manifest(self) -> None:
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": "1.0",
            "store": "JsonlDecisionStore",
            "concurrency_mode": self.concurrency_mode,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "multi_process_safe": self.concurrency_mode == "file_lock",
        }
        self.manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")




def _read_jsonl(path: Path) -> dict[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if not path.is_file():
        return {"records": records, "invalid": invalid}
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                invalid.append({"line": lineno, "error": str(exc)})
                continue
            if isinstance(data, dict):
                records.append(data)
            else:
                invalid.append({"line": lineno, "error": "record is not an object"})
    return {"records": records, "invalid": invalid}


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _duplicate_count(records: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for record in records:
        key_name = next((key for key in ("event_id", "decision_id", "outcome_id", "assessment_id", "feedback_id") if key in record), "")
        if not key_name:
            continue
        key = (key_name, str(record[key_name]))
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _latest_status(events: list[LifecycleTransition]) -> str:
    if not events:
        return ""
    return events[-1].to_status.value
