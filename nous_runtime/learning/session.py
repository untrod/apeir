# -*- coding: utf-8 -*-
"""
Generic Study Session -domain-free session lifecycle.

Wraps nous_core.study_session with a cleaner API that has no domain
knowledge baked in. subject_id and chapter_id are opaque strings
provided by the active Pack.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

log = logging.getLogger("nous.learning.session")


@dataclass
class SessionSummary:
    """Result of ending a study session."""
    session_id: str
    subject_id: str = ""
    chapter_id: str = ""
    duration_minutes: int = 0
    questions_asked: int = 0
    mistakes_recorded: int = 0
    mastery_changes: dict[str, float] = field(default_factory=dict)
    started_at: str = ""
    ended_at: str = ""


class StudySession:
    """
    Generic study session manager.

    Usage:
        sid = StudySession.start(subject_id="math", chapter_id="ch3")
        StudySession.record_question(sid, "What is a limit?")
        StudySession.record_mistake(sid, exercise_id=42, user_answer="x^2", correct="2x")
        summary = StudySession.end(sid)
    """

    @staticmethod
    def start(
        subject_id: str = "",
        chapter_id: str = "",
        goals: str = "",
    ) -> str:
        """
        Start a new study session.

        Args:
            subject_id: Opaque subject identifier (pack-provided).
            chapter_id: Opaque chapter identifier (pack-provided).
            goals: Free-text session goals.

        Returns:
            Session ID string.
        """
        try:
            from nous_runtime.compat.study_session import start_session
            sid = start_session(
                subject=subject_id,
                chapter=chapter_id,
            )
            log.info("Study session started: %s (subject=%s, chapter=%s)",
                     sid, subject_id, chapter_id)
            return sid
        except Exception as e:
            log.warning("Failed to start study session: %s", e)
            import uuid
            return str(uuid.uuid4())

    @staticmethod
    def record_question(session_id: str, question: str) -> None:
        """Record a question asked during the session."""
        try:
            from nous_runtime.compat.study_session import record_question
            record_question(session_id, question)
        except Exception as e:
            log.debug("record_question failed (non-fatal): %s", e)

    @staticmethod
    def record_mistake(
        session_id: str,
        exercise_id: int = 0,
        user_answer: str = "",
        correct: str = "",
        error_type: str = "unknown",
    ) -> None:
        """Record a mistake made during the session."""
        try:
            from nous_runtime.compat.study_session import record_mistake
            record_mistake(session_id, exercise_id, user_answer, correct, error_type)
        except Exception as e:
            log.debug("record_mistake failed (non-fatal): %s", e)

    @staticmethod
    def end(session_id: str) -> SessionSummary:
        """
        End a study session and return a summary.

        Returns:
            SessionSummary with duration, question count, mistake count, etc.
        """
        try:
            from nous_runtime.compat.study_session import end_session
            result = end_session(session_id)
            return SessionSummary(
                session_id=session_id,
                duration_minutes=result.get("duration_minutes", 0) if isinstance(result, dict) else 0,
                questions_asked=result.get("questions", 0) if isinstance(result, dict) else 0,
                mistakes_recorded=result.get("mistakes", 0) if isinstance(result, dict) else 0,
                started_at=result.get("started_at", "") if isinstance(result, dict) else "",
                ended_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        except Exception as e:
            log.warning("end_session failed: %s", e)
            return SessionSummary(session_id=session_id)

    @staticmethod
    def get_active() -> str | None:
        """Return the ID of the currently active session, or None."""
        try:
            from nous_runtime.compat.study_session import get_today_sessions
            sessions = get_today_sessions()
            # Return the most recent un-ended session
            active = [s for s in sessions if isinstance(s, dict) and not s.get("ended_at")]
            return active[-1]["session_id"] if active else None
        except Exception:
            return None
