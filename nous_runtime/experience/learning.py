# -*- coding: utf-8 -*-
"""Experience Learning — lifecycle management and confidence updates.

Lifecycle: NEW → VALIDATED → TRUSTED → DEPRECATED

Promotion rules:
  - NEW → VALIDATED: 3+ occurrences with consistent outcome
  - VALIDATED → TRUSTED: 10+ occurrences, confidence >= 0.80
  - Any → DEPRECATED: success_rate drops below 0.30
"""

from __future__ import annotations

import logging

from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.schema import ExperienceStatus
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.learning")


class ExperienceLearner:
    """Manages experience lifecycle — promotion, demotion, confidence updates.

    Usage::

        learner = ExperienceLearner(store)
        learner.evaluate_and_promote(experience_id)
    """

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()



    def evaluate_and_promote(self, record_id: str) -> ExperienceRecord | None:
        """Evaluate an experience and potentially promote its status."""
        record = self._store.get(record_id)
        if record is None:
            return None

        new_status = self._compute_status(record)
        if new_status != record.status:
            self._store.update_status(record_id, new_status)
            _log.info("Experience %s: %s → %s", record_id, record.status, new_status)
            # Return updated record
            return self._store.get(record_id)

        return record

    def _compute_status(self, record: ExperienceRecord) -> str:
        """Determine the correct lifecycle status."""
        occ = record.occurrence_count
        conf = record.confidence
        success = record.success

        # Deprecation check
        if occ >= 5 and not success and conf < 0.30:
            return ExperienceStatus.DEPRECATED.value

        # Trusted: high occurrence, high confidence
        if occ >= 10 and conf >= 0.80:
            return ExperienceStatus.TRUSTED.value

        # Validated: enough occurrences with consistency
        if occ >= 3:
            return ExperienceStatus.VALIDATED.value

        return ExperienceStatus.NEW.value



    def update_confidence(self, record_id: str, new_evidence_success: bool) -> ExperienceRecord | None:
        """Update confidence based on new evidence."""
        record = self._store.get(record_id)
        if record is None:
            return None

        # Bayesian-like update: weight new evidence at 20%
        old_conf = record.confidence
        new_conf = old_conf * 0.80 + (1.0 if new_evidence_success else 0.0) * 0.20
        new_conf = max(0.05, min(0.99, new_conf))

        # Create updated record
        updated = ExperienceRecord(
            id=record.id, source_type=record.source_type, task_type=record.task_type,
            task_summary=record.task_summary, context_hash=record.context_hash,
            action=record.action, agent_id=record.agent_id, provider_id=record.provider_id,
            result=record.result, evaluation_score=record.evaluation_score,
            success=record.success, failure_reason=record.failure_reason,
            error_code=record.error_code, lessons=record.lessons,
            confidence=new_conf, status=record.status,
            decision_id=record.decision_id, evaluation_id=record.evaluation_id,
            tags=record.tags, occurrence_count=record.occurrence_count + 1,
            created_at=record.created_at, metadata=record.metadata,
        )
        self._store.save(updated)

        # Check for promotion
        return self.evaluate_and_promote(record.id)



    def bulk_evaluate(self, limit: int = 500) -> int:
        """Evaluate and promote all experiences. Returns count of changes."""
        records = self._store.list(limit=limit)
        changes = 0
        for r in records:
            updated = self.evaluate_and_promote(r.id)
            if updated and updated.status != r.status:
                changes += 1
        return changes



    def stats_by_status(self) -> dict[str, int]:
        """Count experiences by status."""
        counts: dict[str, int] = {}
        for status in ExperienceStatus:
            records = self._store.list(status=status.value, limit=10000)
            counts[status.value] = len(records)
        return counts
