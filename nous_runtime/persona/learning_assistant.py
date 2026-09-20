# -*- coding: utf-8 -*-
"""Personal Learning Assistant — tracks study progress, generates review plans,
and organizes learning materials across subjects."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.persona.learning")


# Data models

@dataclass
class Subject:
    name: str
    topics: list[str] = field(default_factory=list)
    mastery_level: float = 0.0  # 0.0 - 1.0
    total_study_hours: float = 0.0
    last_reviewed: str = ""
    notes: str = ""


@dataclass
class StudySession:
    subject: str
    topic: str
    duration_minutes: int = 0
    comprehension_score: float = 0.0  # 0.0 - 1.0
    notes: str = ""
    timestamp: str = ""


@dataclass
class LearningProfile:
    subjects: dict[str, Subject] = field(default_factory=dict)
    sessions: list[StudySession] = field(default_factory=list)
    daily_goal_minutes: int = 120
    preferred_time: str = ""  # e.g., "09:00"
    focus_areas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subjects": {
                k: {
                    "name": v.name,
                    "topics": v.topics,
                    "mastery_level": v.mastery_level,
                    "total_study_hours": v.total_study_hours,
                    "last_reviewed": v.last_reviewed,
                    "notes": v.notes,
                }
                for k, v in self.subjects.items()
            },
            "sessions_count": len(self.sessions),
            "daily_goal_minutes": self.daily_goal_minutes,
            "preferred_time": self.preferred_time,
            "focus_areas": self.focus_areas,
        }


# Learning Assistant

class LearningAssistant:
    """Tracks learning progress and generates personalized study plans.

    Features:
    - Subject and topic tracking with mastery levels
    - Study session logging
    - Spaced repetition scheduling
    - Daily/weekly review plan generation
    - Progress analytics
    """

    def __init__(self, workspace: str | Path = ""):
        self._workspace = (
            Path(workspace) if workspace else Path.home() / ".nous"
        )
        self._data_dir = self._workspace / "learning"
        self._profile_path = self._data_dir / "profile.json"
        self._sessions_path = self._data_dir / "sessions.jsonl"
        self._profile = LearningProfile()
        self._load()

    # Profile management

    def add_subject(
        self,
        name: str,
        topics: list[str] | None = None,
    ) -> Subject:
        """Add a new subject to track."""
        key = name.lower().replace(" ", "_")
        subject = Subject(
            name=name,
            topics=topics or [],
        )
        self._profile.subjects[key] = subject
        self._save()
        return subject

    def add_topic(self, subject_name: str, topic: str) -> None:
        """Add a topic to a subject."""
        key = subject_name.lower().replace(" ", "_")
        if key not in self._profile.subjects:
            self.add_subject(subject_name)
        if topic not in self._profile.subjects[key].topics:
            self._profile.subjects[key].topics.append(topic)
            self._save()

    def set_daily_goal(self, minutes: int) -> None:
        """Set daily study goal in minutes."""
        self._profile.daily_goal_minutes = max(10, min(480, minutes))
        self._save()

    def set_focus_areas(self, areas: list[str]) -> None:
        """Set current focus areas for study."""
        self._profile.focus_areas = areas
        self._save()

    # Session logging

    def log_session(
        self,
        subject: str,
        topic: str,
        duration_minutes: int,
        comprehension_score: float = 0.0,
        notes: str = "",
    ) -> StudySession:
        """Record a completed study session."""
        now = datetime.now(timezone.utc)
        session = StudySession(
            subject=subject,
            topic=topic,
            duration_minutes=max(1, duration_minutes),
            comprehension_score=max(0.0, min(1.0, comprehension_score)),
            notes=notes,
            timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        self._profile.sessions.append(session)

        # Update subject tracking
        key = subject.lower().replace(" ", "_")
        if key not in self._profile.subjects:
            self.add_subject(subject)
        subj = self._profile.subjects[key]
        subj.total_study_hours += duration_minutes / 60.0
        subj.last_reviewed = session.timestamp
        if topic not in subj.topics:
            subj.topics.append(topic)

        # Update mastery (weighted moving average)
        if subj.mastery_level == 0.0:
            subj.mastery_level = comprehension_score
        else:
            subj.mastery_level = (
                subj.mastery_level * 0.7 + comprehension_score * 0.3
            )

        self._save()
        _log.info(
            "Study session logged: %s/%s (%d min, score=%.2f)",
            subject, topic, duration_minutes, comprehension_score,
        )
        return session

    # Review plans

    def generate_daily_plan(self) -> dict[str, Any]:
        """Generate a personalized daily study plan."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Calculate today's study time
        today_sessions = [
            s for s in self._profile.sessions
            if s.timestamp.startswith(today)
        ]
        today_minutes = sum(s.duration_minutes for s in today_sessions)
        remaining = max(0, self._profile.daily_goal_minutes - today_minutes)

        # Prioritize subjects: lowest mastery first, then focus areas
        subjects = sorted(
            self._profile.subjects.values(),
            key=lambda s: s.mastery_level,
        )

        # Prioritize focus areas
        if self._profile.focus_areas:
            focus_keys = {
                a.lower().replace(" ", "_")
                for a in self._profile.focus_areas
            }
            subjects.sort(
                key=lambda s: (
                    0 if s.name.lower().replace(" ", "_") in focus_keys else 1,
                    s.mastery_level,
                )
            )

        recommended = []
        for subj in subjects[:3]:
            # Find least-recently-reviewed topic or lowest-mastery topic
            topics_to_review = subj.topics[:3] if subj.topics else ["general"]
            for topic in topics_to_review:
                recommended.append({
                    "subject": subj.name,
                    "topic": topic,
                    "current_mastery": round(subj.mastery_level, 2),
                    "suggested_duration_min": max(
                        15, min(60, remaining // max(1, len(recommended)))
                    ),
                })

        return {
            "date": today,
            "goal_minutes": self._profile.daily_goal_minutes,
            "completed_minutes": today_minutes,
            "remaining_minutes": remaining,
            "subjects_tracked": len(self._profile.subjects),
            "recommended": recommended[:5],
        }

    def generate_weekly_review(self) -> dict[str, Any]:
        """Generate a weekly learning review."""
        now = datetime.now(timezone.utc)
        week_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Go back to Monday
        days_since_monday = week_start.weekday()
        week_start = datetime.fromtimestamp(
            week_start.timestamp() - days_since_monday * 86400,
            tz=timezone.utc,
        )

        week_sessions = [
            s for s in self._profile.sessions
            if s.timestamp >= week_start.strftime("%Y-%m-%d")
        ]

        total_minutes = sum(s.duration_minutes for s in week_sessions)
        by_subject: dict[str, int] = {}
        by_day: dict[str, int] = {}

        for s in week_sessions:
            by_subject[s.subject] = (
                by_subject.get(s.subject, 0) + s.duration_minutes
            )
            day = s.timestamp[:10]
            by_day[day] = by_day.get(day, 0) + s.duration_minutes

        return {
            "week_start": week_start.strftime("%Y-%m-%d"),
            "total_minutes": total_minutes,
            "sessions_count": len(week_sessions),
            "by_subject": by_subject,
            "by_day": by_day,
            "subjects": {
                k: {
                    "name": v.name,
                    "mastery": round(v.mastery_level, 2),
                    "total_hours": round(v.total_study_hours, 1),
                }
                for k, v in self._profile.subjects.items()
            },
        }

    # Analytics

    def get_progress_summary(self) -> dict[str, Any]:
        """Get overall learning progress summary."""
        total_hours = sum(
            s.total_study_hours
            for s in self._profile.subjects.values()
        )
        total_sessions = len(self._profile.sessions)

        if total_sessions == 0:
            streak = 0
        else:
            # Calculate current streak
            streak = 0
            from datetime import timedelta as td
            check_date = datetime.now(timezone.utc).date()
            dates_with_sessions = {
                s.timestamp[:10] for s in self._profile.sessions
            }
            while check_date.isoformat() in dates_with_sessions:
                streak += 1
                check_date -= td(days=1)

        return {
            "total_hours": round(total_hours, 1),
            "total_sessions": total_sessions,
            "subjects_count": len(self._profile.subjects),
            "current_streak_days": streak,
            "average_mastery": round(
                sum(
                    s.mastery_level
                    for s in self._profile.subjects.values()
                )
                / max(1, len(self._profile.subjects)),
                2,
            ),
            "daily_goal_minutes": self._profile.daily_goal_minutes,
        }

    # Persistence

    def _load(self) -> None:
        """Load learning profile from disk."""
        try:
            if self._profile_path.is_file():
                data = json.loads(
                    self._profile_path.read_text(encoding="utf-8")
                )
                for k, v in data.get("subjects", {}).items():
                    self._profile.subjects[k] = Subject(
                        name=v.get("name", k),
                        topics=v.get("topics", []),
                        mastery_level=v.get("mastery_level", 0.0),
                        total_study_hours=v.get("total_study_hours", 0.0),
                        last_reviewed=v.get("last_reviewed", ""),
                        notes=v.get("notes", ""),
                    )
                self._profile.daily_goal_minutes = data.get(
                    "daily_goal_minutes", 120
                )
                self._profile.preferred_time = data.get("preferred_time", "")
                self._profile.focus_areas = data.get("focus_areas", [])

            if self._sessions_path.is_file():
                for line in self._sessions_path.read_text(
                    encoding="utf-8"
                ).strip().split("\n"):
                    if line.strip():
                        s = json.loads(line)
                        self._profile.sessions.append(StudySession(
                            subject=s.get("subject", ""),
                            topic=s.get("topic", ""),
                            duration_minutes=s.get("duration_minutes", 0),
                            comprehension_score=s.get(
                                "comprehension_score", 0.0
                            ),
                            notes=s.get("notes", ""),
                            timestamp=s.get("timestamp", ""),
                        ))
        except Exception as exc:
            _log.warning("Could not load learning profile: %s", exc)

    def _save(self) -> None:
        """Save learning profile to disk."""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            profile_data = {
                "subjects": {
                    k: {
                        "name": v.name,
                        "topics": v.topics,
                        "mastery_level": v.mastery_level,
                        "total_study_hours": v.total_study_hours,
                        "last_reviewed": v.last_reviewed,
                        "notes": v.notes,
                    }
                    for k, v in self._profile.subjects.items()
                },
                "daily_goal_minutes": self._profile.daily_goal_minutes,
                "preferred_time": self._profile.preferred_time,
                "focus_areas": self._profile.focus_areas,
            }
            self._profile_path.write_text(
                json.dumps(profile_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Append new sessions (only those not yet saved)
            existing_count = 0
            if self._sessions_path.is_file():
                existing_count = len(
                    self._sessions_path.read_text(encoding="utf-8")
                    .strip().split("\n")
                )
            new_sessions = self._profile.sessions[existing_count:]
            if new_sessions:
                with open(
                    self._sessions_path, "a", encoding="utf-8"
                ) as f:
                    for s in new_sessions:
                        f.write(json.dumps({
                            "subject": s.subject,
                            "topic": s.topic,
                            "duration_minutes": s.duration_minutes,
                            "comprehension_score": s.comprehension_score,
                            "notes": s.notes,
                            "timestamp": s.timestamp,
                        }, ensure_ascii=False) + "\n")
        except Exception as exc:
            _log.warning("Could not save learning profile: %s", exc)


# Convenience functions

def create_learning_assistant(
    workspace: str | Path = "",
) -> LearningAssistant:
    """Create a learning assistant for the given workspace."""
    return LearningAssistant(workspace)


__all__ = [
    "Subject",
    "StudySession",
    "LearningProfile",
    "LearningAssistant",
    "create_learning_assistant",
]
