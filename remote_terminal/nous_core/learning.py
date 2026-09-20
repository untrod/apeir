# -*- coding: utf-8 -*-
"""
Learning State Model — unified view of all learning data.

Reads from the existing learn_data.db tables and computes:
  - Mastery level per subject, chapter, and knowledge point
  - Weakness scores (derived from mistakes + low mastery + overdue review)
  - Review due queue (sorted by urgency)
  - Evidence trail (what was studied when)

Design: This is a READ-ONLY analytics layer. It does NOT modify learn_data.db.
All writes go through the existing learn_db.py / learn_tools.py.
"""

from __future__ import annotations

import sqlite3 as _sqlite3
import os as _os
from typing import Any
from datetime import datetime as _dt, timezone as _tz

_LEARN_DB = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                           "learn_data.db")


def _connect(readonly: bool = True):
    """Open read-only connection to learn_data.db."""
    path = f"file:{_LEARN_DB}?mode=ro" if readonly else _LEARN_DB
    conn = _sqlite3.connect(path, uri=readonly)
    conn.row_factory = _sqlite3.Row
    return conn


# Subject Overview

def get_subject_summary() -> list[dict[str, Any]]:
    """Return per-subject statistics from all data sources."""
    summaries = []
    try:
        db = _connect()
        # Knowledge points per subject
        kp_rows = db.execute("""
            SELECT subject, COUNT(*) as total,
                   AVG(mastery) as avg_mastery,
                   SUM(CASE WHEN mastery < 0.3 THEN 1 ELSE 0 END) as weak_count,
                   SUM(CASE WHEN mastery >= 0.7 THEN 1 ELSE 0 END) as mastered_count,
                   SUM(CASE WHEN next_review != '' AND next_review <= datetime('now')
                       THEN 1 ELSE 0 END) as review_due
            FROM knowledge_points WHERE subject != ''
            GROUP BY subject ORDER BY avg_mastery ASC
        """).fetchall()

        # Exercises
        ex_rows = db.execute("""
            SELECT kp.subject, COUNT(*) as total_exercises
            FROM exercises e JOIN knowledge_points kp ON e.knowledge_point_id = kp.id
            WHERE kp.subject != '' GROUP BY kp.subject
        """).fetchall()
        ex_map = {r["subject"]: r["total_exercises"] for r in ex_rows}

        # Mistakes
        mk_rows = db.execute("""
            SELECT kp.subject, COUNT(*) as total_mistakes,
                   SUM(CASE WHEN m.reviewed = 0 THEN 1 ELSE 0 END) as unreviewed
            FROM mistake_records m
            JOIN exercises e ON m.exercise_id = e.id
            JOIN knowledge_points kp ON e.knowledge_point_id = kp.id
            WHERE kp.subject != '' GROUP BY kp.subject
        """).fetchall()
        mk_map = {r["subject"]: {"total": r["total_mistakes"], "unreviewed": r["unreviewed"]}
                  for r in mk_rows}

        # Formulas
        fm_rows = db.execute("""
            SELECT subject, COUNT(*) as total,
                   AVG(mastery) as avg_mastery
            FROM formulas WHERE subject != ''
            GROUP BY subject
        """).fetchall()
        fm_map = {r["subject"]: {"total": r["total"], "avg_mastery": r["avg_mastery"]}
                  for r in fm_rows}

        # Progress log (today)
        today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
        pg_rows = db.execute("""
            SELECT subject, SUM(study_minutes) as minutes_today,
                   SUM(exercises_done) as done_today,
                   SUM(exercises_correct) as correct_today
            FROM progress_log WHERE date = ? AND subject != ''
            GROUP BY subject
        """, (today,)).fetchall()
        pg_map = {}
        for r in pg_rows:
            pg_map[r["subject"]] = {
                "minutes_today": r["minutes_today"] or 0,
                "done_today": r["done_today"] or 0,
                "correct_today": r["correct_today"] or 0,
            }

        db.close()

        for r in kp_rows:
            subj = r["subject"]
            mk = mk_map.get(subj, {"total": 0, "unreviewed": 0})
            fm = fm_map.get(subj, {"total": 0, "avg_mastery": 0})
            pg = pg_map.get(subj, {"minutes_today": 0, "done_today": 0, "correct_today": 0})

            summaries.append({
                "subject": subj,
                "knowledge_points": r["total"],
                "avg_mastery": round(r["avg_mastery"] or 0, 2),
                "weak_count": r["weak_count"],
                "mastered_count": r["mastered_count"],
                "review_due": r["review_due"],
                "exercises": ex_map.get(subj, 0),
                "total_mistakes": mk["total"],
                "unreviewed_mistakes": mk["unreviewed"],
                "formulas": fm["total"],
                "formula_mastery": round(fm["avg_mastery"] or 0, 2),
                **pg,
            })

    except Exception:
        pass
    return summaries


# Weakness Analysis

def get_weakness_ranking(limit: int = 20) -> list[dict[str, Any]]:
    """
    Rank the weakest areas by a composite score:
      weakness = (1 - mastery) * 0.4 + mistake_rate * 0.3 + review_overdue * 0.3
    """
    items = []
    try:
        db = _connect()
        rows = db.execute("""
            SELECT kp.id, kp.subject, kp.chapter, kp.section, kp.title,
                   kp.mastery, kp.review_count,
                   CASE WHEN kp.next_review != '' AND kp.next_review <= datetime('now')
                        THEN 1 ELSE 0 END as is_overdue,
                   (SELECT COUNT(*) FROM exercises e WHERE e.knowledge_point_id = kp.id) as ex_count,
                   (SELECT COUNT(*) FROM exercises e
                    JOIN mistake_records m ON m.exercise_id = e.id
                    WHERE e.knowledge_point_id = kp.id) as mistake_count
            FROM knowledge_points kp
            WHERE kp.subject != ''
            ORDER BY kp.mastery ASC, is_overdue DESC
            LIMIT ?
        """, (limit * 2,)).fetchall()
        db.close()

        for r in rows:
            mistake_rate = r["mistake_count"] / max(r["ex_count"], 1)
            weakness = round(
                (1 - (r["mastery"] or 0)) * 0.4 +
                mistake_rate * 0.3 +
                r["is_overdue"] * 0.3, 3
            )
            if weakness > 0.15:
                items.append({
                    "kp_id": r["id"],
                    "subject": r["subject"],
                    "chapter": r["chapter"] or "",
                    "section": r["section"] or "",
                    "title": r["title"] or "",
                    "mastery": round(r["mastery"] or 0, 2),
                    "review_count": r["review_count"],
                    "is_overdue": bool(r["is_overdue"]),
                    "mistake_count": r["mistake_count"],
                    "weakness_score": weakness,
                })
    except Exception:
        pass
    return sorted(items, key=lambda x: x["weakness_score"], reverse=True)[:limit]


# Review Queue

def get_review_queue(subject: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """
    Get items due for review, sorted by urgency (most overdue first).

    Includes knowledge points AND formulas.
    """
    items = []
    try:
        db = _connect()

        # Knowledge points due for review
        kp_where = "WHERE next_review != '' AND next_review <= datetime('now')"
        kp_params: list[Any] = []
        if subject:
            kp_where += " AND subject = ?"
            kp_params.append(subject)

        kp_rows = db.execute(f"""
            SELECT id, subject, chapter, section, title, mastery, review_count,
                   last_reviewed, next_review,
                   CAST(julianday('now') - julianday(next_review) AS INTEGER) as days_overdue
            FROM knowledge_points {kp_where}
            ORDER BY days_overdue DESC
            LIMIT ?
        """, kp_params + [limit]).fetchall()

        for r in kp_rows:
            items.append({
                "type": "knowledge_point",
                "id": r["id"], "subject": r["subject"],
                "chapter": r["chapter"] or "", "title": r["title"] or "",
                "mastery": round(r["mastery"] or 0, 2),
                "review_count": r["review_count"],
                "last_reviewed": r["last_reviewed"],
                "days_overdue": r["days_overdue"] or 0,
            })

        # Formulas due for review
        fm_where = "WHERE next_review != '' AND next_review <= datetime('now')"
        fm_params = []
        if subject:
            fm_where += " AND subject = ?"
            fm_params.append(subject)

        fm_rows = db.execute(f"""
            SELECT id, subject, name, latex, mastery, review_count,
                   last_reviewed, next_review,
                   CAST(julianday('now') - julianday(next_review) AS INTEGER) as days_overdue
            FROM formulas {fm_where}
            ORDER BY days_overdue DESC
            LIMIT ?
        """, fm_params + [limit]).fetchall()

        for r in fm_rows:
            items.append({
                "type": "formula",
                "id": r["id"], "subject": r["subject"],
                "title": r["name"] or r["latex"] or "",
                "mastery": round(r["mastery"] or 0, 2),
                "review_count": r["review_count"],
                "last_reviewed": r["last_reviewed"],
                "days_overdue": r["days_overdue"] or 0,
            })

        db.close()
    except Exception:
        pass

    return sorted(items, key=lambda x: x["days_overdue"], reverse=True)[:limit]


# Chapter-Level State

def get_chapter_state(subject: str) -> list[dict[str, Any]]:
    """Get per-chapter learning state for a subject."""
    chapters = []
    try:
        db = _connect()
        rows = db.execute("""
            SELECT chapter,
                   COUNT(*) as total_kp,
                   AVG(mastery) as avg_mastery,
                   SUM(CASE WHEN next_review != '' AND next_review <= datetime('now')
                       THEN 1 ELSE 0 END) as review_due,
                   SUM(CASE WHEN mastery < 0.3 THEN 1 ELSE 0 END) as weak_count,
                   MAX(last_reviewed) as last_studied
            FROM knowledge_points
            WHERE subject = ? AND chapter != ''
            GROUP BY chapter
            ORDER BY avg_mastery ASC
        """, (subject,)).fetchall()
        db.close()

        for r in rows:
            chapters.append({
                "chapter": r["chapter"],
                "total_kp": r["total_kp"],
                "avg_mastery": round(r["avg_mastery"] or 0, 2),
                "review_due": r["review_due"],
                "weak_count": r["weak_count"],
                "last_studied": r["last_studied"] or "",
            })
    except Exception:
        pass
    return chapters


# Overall Stats

def get_overall_stats() -> dict[str, Any]:
    """Get high-level stats for dashboard."""
    try:
        db = _connect()
        total_kp = db.execute("SELECT COUNT(*) as n FROM knowledge_points").fetchone()["n"]
        total_ex = db.execute("SELECT COUNT(*) as n FROM exercises").fetchone()["n"]
        total_fm = db.execute("SELECT COUNT(*) as n FROM formulas").fetchone()["n"]
        total_docs = db.execute("SELECT COUNT(*) as n FROM documents").fetchone()["n"]

        avg_mastery = db.execute(
            "SELECT AVG(mastery) as n FROM knowledge_points WHERE mastery > 0"
        ).fetchone()["n"] or 0

        review_due = db.execute(
            "SELECT COUNT(*) as n FROM knowledge_points "
            "WHERE next_review != '' AND next_review <= datetime('now')"
        ).fetchone()["n"]

        today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
        today_minutes = db.execute(
            "SELECT SUM(study_minutes) as n FROM progress_log WHERE date = ?", (today,)
        ).fetchone()["n"] or 0
        today_ex = db.execute(
            "SELECT SUM(exercises_done) as n FROM progress_log WHERE date = ?", (today,)
        ).fetchone()["n"] or 0

        streak = _compute_streak(db)

        db.close()

        return {
            "total_knowledge_points": total_kp,
            "total_exercises": total_ex,
            "total_formulas": total_fm,
            "total_documents": total_docs,
            "avg_mastery": round(avg_mastery, 2),
            "review_due_today": review_due,
            "study_minutes_today": today_minutes,
            "exercises_today": today_ex,
            "current_streak": streak,
        }
    except Exception:
        return {}


def _compute_streak(db) -> int:
    """Compute consecutive days with study activity."""
    streak = 0
    try:
        rows = db.execute(
            "SELECT DISTINCT date FROM progress_log ORDER BY date DESC LIMIT 30"
        ).fetchall()
        if not rows:
            return 0
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
        expected = today
        for r in rows:
            if r["date"] == expected:
                streak += 1
                # Move expected back one day
                expected = _dt.strftime(
                    _dt.strptime(expected, "%Y-%m-%d") - __import__("datetime").timedelta(days=1),
                    "%Y-%m-%d")
            elif r["date"] < expected:
                break
    except Exception:
        pass
    return streak
