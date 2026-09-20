# -*- coding: utf-8 -*-
"""
Daily Report Generator — comprehensive end-of-day summary.

Generates:
  - Today's completed tasks
  - Weakness evolution (what improved, what got worse)
  - Review compliance (% of due items actually reviewed)
  - Tomorrow's suggested plan
  - Long-term trend (last 7 days)

Usage:
  from nous_core.daily_report import generate_daily_report

  report = generate_daily_report()
  print(report["summary_text"])
"""

from __future__ import annotations

import os as _os
import sqlite3 as _sqlite3
from typing import Any
from datetime import datetime as _dt, timezone as _tz, timedelta as _td


_LEARN_DB = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                           "learn_data.db")


def _lconnect(readonly: bool = True):
    path = f"file:{_LEARN_DB}?mode=ro" if readonly else _LEARN_DB
    conn = _sqlite3.connect(path, uri=readonly)
    conn.row_factory = _sqlite3.Row
    return conn


def generate_daily_report() -> dict[str, Any]:
    """Generate a complete daily report."""
    today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
    yesterday = (_dt.now(tz=_tz.utc) - _td(days=1)).strftime("%Y-%m-%d")

    report = {
        "date": today,
        "today": _today_summary(today),
        "weakness": _weakness_evolution(today),
        "review_compliance": _review_compliance(today),
        "study_sessions": _today_sessions(today),
        "tomorrow_plan": _tomorrow_suggestions(),
        "trend": _seven_day_trend(),
        "summary_text": "",
    }

    # Generate readable summary
    t = report["today"]
    report["summary_text"] = (
        f"📅 {today} 学习报告\n"
        f"⏱️ 学习 {t.get('minutes', 0)} 分钟 · "
        f"📝 {t.get('exercises', 0)} 题 (正确率 {t.get('accuracy', 0)}%)\n"
        f"📚 {t.get('kps_reviewed', 0)} 知识点已复习 · "
        f"🔁 {t.get('review_due_remaining', 0)} 待复习\n"
        f"❌ {t.get('mistakes_today', 0)} 错题新增\n"
        f"📊 连续学习 {report['trend'].get('streak', 0)} 天"
    )

    return report


def _today_summary(today: str) -> dict:
    try:
        db = _lconnect()
        row = db.execute("""
            SELECT SUM(study_minutes) as minutes,
                   SUM(exercises_done) as exercises,
                   SUM(exercises_correct) as correct,
                   SUM(formulas_reviewed) as formulas
            FROM progress_log WHERE date = ?
        """, (today,)).fetchone()
        db.close()

        ex = row["exercises"] or 0
        cor = row["correct"] or 0
        # Review due remaining
        db2 = _lconnect()
        due = db2.execute(
            "SELECT COUNT(*) as n FROM knowledge_points "
            "WHERE next_review != '' AND next_review <= datetime('now')"
        ).fetchone()["n"]
        # Mistakes today
        mt = db2.execute(
            "SELECT COUNT(*) as n FROM mistake_records WHERE date(created_at) = ?", (today,)
        ).fetchone()["n"]
        # KPs reviewed today
        kpr = db2.execute(
            "SELECT COUNT(*) as n FROM knowledge_points WHERE last_reviewed LIKE ?",
            (today + "%",)
        ).fetchone()["n"]
        db2.close()

        return {
            "minutes": row["minutes"] or 0,
            "exercises": ex,
            "exercises_correct": cor,
            "accuracy": round(cor / max(ex, 1) * 100, 1),
            "formulas_reviewed": row["formulas"] or 0,
            "kps_reviewed": kpr,
            "review_due_remaining": due,
            "mistakes_today": mt,
        }
    except Exception:
        return {}


def _weakness_evolution(today: str) -> dict:
    """Track weakness changes: improved vs worsened subjects."""
    try:
        from .learning import get_subject_summary
        subjects = get_subject_summary()
        improved = [s for s in subjects if s.get("mastered_count", 0) > s.get("weak_count", 0)]
        weak = [s for s in subjects if s.get("weak_count", 0) > 0]
        return {
            "improving_subjects": [s["subject"] for s in improved[:5]],
            "weak_subjects": [s["subject"] for s in weak[:5]],
            "weakest_topic": weak[0]["subject"] if weak else "",
            "overall_avg_mastery": round(
                sum(s["avg_mastery"] for s in subjects) / max(len(subjects), 1), 2
            ),
        }
    except Exception:
        return {}


def _review_compliance(today: str) -> dict:
    """What % of due reviews were actually done today?"""
    try:
        db = _lconnect()
        total_due = db.execute(
            "SELECT COUNT(*) as n FROM knowledge_points "
            "WHERE next_review <= ?", (today + "T23:59:59Z",)
        ).fetchone()["n"]
        done_today = db.execute(
            "SELECT COUNT(*) as n FROM knowledge_points WHERE last_reviewed LIKE ?",
            (today + "%",)
        ).fetchone()["n"]
        db.close()
        return {
            "total_due": total_due,
            "done_today": done_today,
            "compliance_pct": round(done_today / max(total_due, 1) * 100, 1),
        }
    except Exception:
        return {}


def _today_sessions(today: str) -> list[dict]:
    try:
        from .study_session import get_today_sessions
        return get_today_sessions()
    except Exception:
        return []


def _tomorrow_suggestions() -> dict:
    """Use the enhanced plan engine to suggest tomorrow's plan."""
    try:
        from nous_core.learning import get_review_queue, get_weakness_ranking
        review = get_review_queue(limit=5)
        weak = get_weakness_ranking(limit=5)
        return {
            "top_reviews": [{"title": r["title"][:40], "subject": r["subject"],
                             "days_overdue": r["days_overdue"]} for r in review[:3]],
            "top_weakness": [{"title": w["title"][:40], "subject": w["subject"],
                              "score": w["weakness_score"]} for w in weak[:3]],
            "suggested_minutes": 90 + len(review) * 10,
        }
    except Exception:
        return {}


def _seven_day_trend() -> dict:
    """Last 7 days of study activity."""
    days = []
    try:
        db = _lconnect()
        for i in range(6, -1, -1):
            d = (_dt.now(tz=_tz.utc) - _td(days=i)).strftime("%Y-%m-%d")
            row = db.execute(
                "SELECT SUM(study_minutes) as m, SUM(exercises_done) as e "
                "FROM progress_log WHERE date = ?", (d,)
            ).fetchone()
            days.append({
                "date": d,
                "minutes": row["m"] or 0,
                "exercises": row["e"] or 0,
            })

        # Streak
        streak = 0
        today = _dt.now(tz=_tz.utc).strftime("%Y-%m-%d")
        for day in reversed(days):
            if day["minutes"] > 0:
                streak += 1
            else:
                if day["date"] != today:
                    break

        db.close()
        return {
            "days": days,
            "streak": streak,
            "total_minutes_7d": sum(d["minutes"] for d in days),
            "total_exercises_7d": sum(d["exercises"] for d in days),
        }
    except Exception:
        return {"days": [], "streak": 0, "total_minutes_7d": 0, "total_exercises_7d": 0}
