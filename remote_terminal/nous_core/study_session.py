# -*- coding: utf-8 -*-
"""
Study Session Tracker — track start/end, questions, mistakes, auto-summarize.

Integrates with:
  - nous_core.learning for state queries
  - nous_core.capture for question recording (inbox)
  - nous_core.jobs for post-session review creation
  - learn_db for progress_log updates

Usage:
  from nous_core.study_session import start_session, record_question, record_mistake, end_session

  sid = start_session(subject="Math", chapter="Chapter 3")
  record_question(sid, "链式法则和普通求导有什么区别？")
  record_mistake(sid, exercise_id=42, user_answer="x^2", correct="2x", error_type="concept")
  summary = end_session(sid)
"""

from __future__ import annotations

import logging as _logging
import os as _os
import sqlite3 as _sqlite3
from typing import Any
from datetime import datetime as _dt, timezone as _tz

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.study_session")

# Learn DB path for progress_log writes
_LEARN_DB = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                           "learn_data.db")


def start_session(
    subject: str = "",
    chapter: str = "",
    goals: str = "",
) -> str:
    """Start a study session. Returns session ID (ssn_YYYYMMDD_XXXXXXXX)."""
    sid = _ids.make_id("ssn")
    now = _time.utc_now()
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO study_sessions (id, subject, chapter, goals, status,
                   started_at, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?)""",
                (sid, subject, chapter, goals, now, now),
            )
        _log.info("Study session started: %s [%s/%s]", sid, subject or "general",
                  chapter or "")
        return sid
    except Exception as e:
        _log.error("start_session failed: %s", e)
        return ""


def record_question(session_id: str, question: str, answer: str = "") -> str:
    """Record a question asked during the study session."""
    qid = _ids.make_id("stq")
    now = _time.utc_now()
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO session_questions (id, session_id, question, answer,
                   created_at) VALUES (?, ?, ?, ?, ?)""",
                (qid, session_id, question[:1000], answer[:2000], now),
            )
        return qid
    except Exception:
        return ""


def record_mistake(
    session_id: str,
    exercise_id: int = 0,
    user_answer: str = "",
    correct_answer: str = "",
    error_type: str = "",
    note: str = "",
) -> str:
    """Record a mistake made during the study session."""
    mid = _ids.make_id("stm")
    now = _time.utc_now()
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO session_mistakes (id, session_id, exercise_id,
                   user_answer, correct_answer, error_type, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, session_id, exercise_id, user_answer[:500],
                 correct_answer[:500], error_type, note[:500], now),
            )
        return mid
    except Exception:
        return ""


def record_progress(
    session_id: str,
    minutes: int = 0,
    exercises_done: int = 0,
    exercises_correct: int = 0,
    subject: str = "",
):
    """Record a progress update during the session."""
    try:
        with _connect() as db:
            db.execute(
                "UPDATE study_sessions SET minutes = minutes + ?, "
                "exercises_done = exercises_done + ?, "
                "exercises_correct = exercises_correct + ? "
                "WHERE id = ?",
                (minutes, exercises_done, exercises_correct, session_id),
            )
        # Also write to learn_data.db progress_log
        if subject:
            _write_progress_log(subject, minutes, exercises_done, exercises_correct)
    except Exception as e:
        _log.warning("record_progress: %s", e)


def _write_progress_log(subject: str, minutes: int, done: int, correct: int):
    """Write to learn_data.db progress_log table."""
    today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
    try:
        ldb = _sqlite3.connect(_LEARN_DB)
        ldb.execute(
            """INSERT INTO progress_log (date, subject, study_minutes, exercises_done,
               exercises_correct) VALUES (?, ?, ?, ?, ?)""",
            (today, subject, minutes, done, correct),
        )
        ldb.commit()
        ldb.close()
    except Exception:
        pass


def end_session(session_id: str) -> dict[str, Any]:
    """End a study session and generate summary."""
    now = _time.utc_now()
    summary = {}
    try:
        with _connect() as db:
            # Mark session complete
            db.execute(
                "UPDATE study_sessions SET status = 'completed', ended_at = ? "
                "WHERE id = ?", (now, session_id),
            )

            # Read session data
            row = db.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            questions = db.execute(
                "SELECT COUNT(*) as n FROM session_questions WHERE session_id = ?",
                (session_id,)
            ).fetchone()["n"]
            mistakes = db.execute(
                "SELECT * FROM session_mistakes WHERE session_id = ?", (session_id,)
            ).fetchall()

            if row:
                summary = {
                    "session_id": session_id,
                    "subject": row["subject"],
                    "chapter": row["chapter"],
                    "minutes": row["minutes"] or 0,
                    "exercises_done": row["exercises_done"] or 0,
                    "exercises_correct": row["exercises_correct"] or 0,
                    "questions_asked": questions,
                    "mistakes_made": len(mistakes),
                    "accuracy": round(
                        (row["exercises_correct"] or 0) / max(row["exercises_done"] or 1, 1) * 100, 1
                    ),
                    "error_types": list(set(m["error_type"] for m in mistakes if m["error_type"])),
                    "started_at": row["started_at"],
                    "ended_at": now,
                }

            # Create review job for mistakes
            if mistakes:
                try:
                    from .jobs import create_job
                    create_job(
                        "review_mistakes",
                        source="study_session",
                        session_id=session_id,
                        payload={
                            "mistake_count": len(mistakes),
                            "error_types": summary.get("error_types", []),
                            "session_subject": summary.get("subject", ""),
                            "action": "generate_mistake_review",
                        },
                        timeout_sec=600,
                    )
                except Exception:
                    pass

        _log.info("Study session ended: %s (%d min, %d ex, %d mistakes)",
                  session_id, summary.get("minutes", 0),
                  summary.get("exercises_done", 0), summary.get("mistakes_made", 0))

    except Exception as e:
        _log.error("end_session failed: %s", e)

    return summary


def get_today_sessions() -> list[dict[str, Any]]:
    """Get all study sessions from today."""
    today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM study_sessions WHERE date(created_at) = ? "
                "ORDER BY started_at DESC", (today,)
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    """Get full detail of a study session including questions and mistakes."""
    try:
        with _connect(readonly=True) as db:
            session = db.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                return None
            questions = db.execute(
                "SELECT * FROM session_questions WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            ).fetchall()
            mistakes = db.execute(
                "SELECT * FROM session_mistakes WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            ).fetchall()
            return {
                **_row_to_dict(session),
                "questions": [_row_to_dict(q) for q in questions],
                "mistakes": [_row_to_dict(m) for m in mistakes],
            }
    except Exception:
        return None


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row else {}
