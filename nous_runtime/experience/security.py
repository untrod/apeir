# -*- coding: utf-8 -*-
"""Experience Security — protects experience integrity.

Rules:
  1. Agents can READ experiences (for learning)
  2. Agents CANNOT write, modify, or delete experiences
  3. System can write (auto-collection)
  4. New experiences start at NEW status — never auto-trusted
  5. Single-failure does NOT create a rule (min 3 occurrences)
  6. Injection filtering prevents malicious experiences
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.schema import ExperienceStatus

_log = logging.getLogger("nous.experience.security")

MIN_OCCURRENCES_FOR_VALIDATION = 3
MIN_OCCURRENCES_FOR_TRUST = 10


@dataclass
class ExperienceAccessRequest:
    actor: str = ""
    actor_type: str = ""   # "agent", "user", "system"
    action: str = ""       # "read", "write", "modify", "delete"
    record_id: str = ""
    purpose: str = ""


@dataclass
class ExperienceAccessDecision:
    allowed: bool = False
    reason: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ExperienceGuard:
    """Protects experience data from unauthorized modification.

    Rules:
      - agent: READ only
      - user: READ, WRITE
      - system: READ, WRITE, MODIFY, DELETE
    """

    PERMISSIONS = {
        "system": {"read", "write", "modify", "delete"},
        "user": {"read", "write"},
        "agent": {"read"},
    }

    def authorize(self, request: ExperienceAccessRequest) -> ExperienceAccessDecision:
        allowed = self.PERMISSIONS.get(request.actor_type, set())

        if request.action not in allowed:
            return ExperienceAccessDecision(
                allowed=False,
                reason=f"Actor '{request.actor_type}' cannot '{request.action}' experiences.",
            )

        # Agents cannot write experiences
        if request.actor_type == "agent" and request.action in ("write", "modify", "delete"):
            return ExperienceAccessDecision(
                allowed=False,
                reason="Agents cannot modify experience data.",
            )

        return ExperienceAccessDecision(allowed=True, reason=f"{request.action} granted.")



    @staticmethod
    def validate_experience(record: ExperienceRecord) -> list[str]:
        """Validate an experience before saving. Returns list of violations."""
        violations: list[str] = []

        # Required fields
        if not record.task_type:
            violations.append("task_type is required")
        if not record.action:
            violations.append("action is required")
        if not record.source_type:
            violations.append("source_type is required")

        # Single-failure guard: a new experience with failure must have a reason
        if not record.success and not record.failure_reason:
            violations.append("Failed experiences must have a failure_reason")

        # Confidence bounds
        if record.confidence < 0.0 or record.confidence > 1.0:
            violations.append("confidence must be 0.0–1.0")

        # Status promotion guard: cannot jump directly to TRUSTED
        if record.status == ExperienceStatus.TRUSTED.value and record.occurrence_count < MIN_OCCURRENCES_FOR_TRUST:
            violations.append(
                f"Experience needs {MIN_OCCURRENCES_FOR_TRUST}+ occurrences for TRUSTED status "
                f"(has {record.occurrence_count})"
            )

        return violations

    @staticmethod
    def filter_injection(text: str) -> str:
        """Filter potentially malicious content from experience text."""
        # Strip control characters, limit length
        cleaned = "".join(c for c in text if c.isprintable() or c in "\n\t ")
        return cleaned[:2000]
