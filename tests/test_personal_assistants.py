# -*- coding: utf-8 -*-
"""Tests for the Learning and Project personal assistants."""

from __future__ import annotations

import tempfile

import pytest

from nous_runtime.persona.learning_assistant import (
    Subject,
    LearningAssistant,
    create_learning_assistant,
)
from nous_runtime.persona.project_assistant import (
    ProjectMilestone,
    ProjectAssistant,
    create_project_assistant,
)


# Learning Assistant Tests

class TestSubject:
    def test_create_subject(self):
        s = Subject(name="Mathematics", topics=["Algebra", "Calculus"])
        assert s.name == "Mathematics"
        assert len(s.topics) == 2
        assert s.mastery_level == 0.0


class TestLearningAssistant:
    @pytest.fixture
    def assistant(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield LearningAssistant(workspace=tmp)

    def test_add_subject(self, assistant):
        s = assistant.add_subject("Math", ["Algebra"])
        assert s.name == "Math"
        assert "math" in assistant._profile.subjects

    def test_add_topic(self, assistant):
        assistant.add_subject("Math")
        assistant.add_topic("Math", "Calculus")
        assert "Calculus" in assistant._profile.subjects["math"].topics

    def test_add_topic_creates_subject(self, assistant):
        assistant.add_topic("Physics", "Mechanics")
        assert "physics" in assistant._profile.subjects

    def test_set_daily_goal(self, assistant):
        assistant.set_daily_goal(180)
        assert assistant._profile.daily_goal_minutes == 180

    def test_set_daily_goal_clamped(self, assistant):
        assistant.set_daily_goal(5)
        assert assistant._profile.daily_goal_minutes == 10  # Min 10

        assistant.set_daily_goal(1000)
        assert assistant._profile.daily_goal_minutes == 480  # Max 480

    def test_set_focus_areas(self, assistant):
        assistant.set_focus_areas(["Math", "Programming"])
        assert "Math" in assistant._profile.focus_areas

    def test_log_session(self, assistant):
        session = assistant.log_session(
            subject="Math",
            topic="Algebra",
            duration_minutes=45,
            comprehension_score=0.8,
        )
        assert session.subject == "Math"
        assert session.duration_minutes == 45
        assert len(assistant._profile.sessions) == 1
        assert assistant._profile.subjects["math"].total_study_hours > 0

    def test_log_session_updates_mastery(self, assistant):
        assistant.log_session("Math", "Algebra", 30, 0.5)
        s = assistant._profile.subjects["math"]
        assert s.mastery_level > 0.0

        assistant.log_session("Math", "Algebra", 30, 0.9)
        s = assistant._profile.subjects["math"]
        assert s.mastery_level > 0.5  # Should increase

    def test_log_session_creates_subject(self, assistant):
        assistant.log_session("NewSubject", "Topic", 20, 0.7)
        assert "newsubject" in assistant._profile.subjects

    def test_generate_daily_plan_empty(self, assistant):
        plan = assistant.generate_daily_plan()
        assert "date" in plan
        assert "goal_minutes" in plan
        assert "remaining_minutes" in plan
        assert plan["remaining_minutes"] == plan["goal_minutes"]

    def test_generate_daily_plan_with_sessions(self, assistant):
        assistant.log_session("Math", "Algebra", 60, 0.8)
        plan = assistant.generate_daily_plan()
        assert plan["completed_minutes"] == 60
        assert plan["remaining_minutes"] == plan["goal_minutes"] - 60

    def test_generate_weekly_review(self, assistant):
        assistant.log_session("Math", "Algebra", 30, 0.8)
        review = assistant.generate_weekly_review()
        assert "week_start" in review
        assert "total_minutes" in review
        assert review["total_minutes"] >= 30

    def test_get_progress_summary(self, assistant):
        summary = assistant.get_progress_summary()
        assert summary["total_sessions"] == 0
        assert summary["total_hours"] == 0.0

        assistant.log_session("Math", "Topic", 60, 0.9)
        summary = assistant.get_progress_summary()
        assert summary["total_sessions"] == 1
        assert summary["total_hours"] > 0

    def test_persistence(self, assistant):
        assistant.add_subject("Math", ["Algebra"])
        assistant.log_session("Math", "Algebra", 30, 0.8)

        # Create a new assistant pointing to the same workspace
        ws = assistant._workspace
        assistant2 = LearningAssistant(workspace=ws)
        assert "math" in assistant2._profile.subjects
        assert len(assistant2._profile.sessions) >= 1


class TestCreateLearningAssistant:
    def test_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = create_learning_assistant(tmp)
            assert isinstance(a, LearningAssistant)


# Project Assistant Tests

class TestProjectMilestone:
    def test_create(self):
        m = ProjectMilestone(name="MVP", description="First release")
        assert m.name == "MVP"
        assert m.completed is False

    def test_complete(self):
        m = ProjectMilestone(name="MVP")
        m.completed = True
        m.completed_at = "2026-07-27T00:00:00Z"
        assert m.completed is True


class TestProjectAssistant:
    @pytest.fixture
    def assistant(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield ProjectAssistant(workspace=tmp)

    def test_create_project(self, assistant):
        p = assistant.create_project(
            "Nous Runtime",
            "AI Runtime development",
            priority="high",
            tags=["ai", "runtime"],
        )
        assert p.name == "Nous Runtime"
        assert p.status == "active"
        assert "ai" in p.tags

    def test_create_duplicate_project(self, assistant):
        assistant.create_project("Test")
        with pytest.raises(ValueError):
            assistant.create_project("Test")

    def test_get_project(self, assistant):
        assistant.create_project("Test Project")
        p = assistant.get_project("Test Project")
        assert p is not None
        assert p.name == "Test Project"

    def test_get_nonexistent_project(self, assistant):
        p = assistant.get_project("No Such Project")
        assert p is None

    def test_list_projects(self, assistant):
        assistant.create_project("Project A")
        assistant.create_project("Project B")
        projects = assistant.list_projects()
        assert len(projects) == 2

    def test_list_projects_filtered(self, assistant):
        assistant.create_project("Active Project", priority="high")
        assistant.create_project("Paused Project")
        assistant.update_status("Paused Project", "paused")

        active = assistant.list_projects(status="active")
        paused = assistant.list_projects(status="paused")
        assert len(active) >= 1
        assert len(paused) >= 1

        high = assistant.list_projects(priority="high")
        assert len(high) >= 1

    def test_update_status(self, assistant):
        assistant.create_project("Test")
        p = assistant.update_status("Test", "paused", "Taking a break")
        assert p is not None
        assert p.status == "paused"
        assert "Taking a break" in p.notes

    def test_add_milestone(self, assistant):
        assistant.create_project("Test")
        m = assistant.add_milestone(
            "Test", "Phase 1", "Complete phase 1", "2026-08-01"
        )
        assert m is not None
        assert m.name == "Phase 1"

        project = assistant.get_project("Test")
        assert len(project.milestones) == 1

    def test_add_milestone_nonexistent_project(self, assistant):
        m = assistant.add_milestone("Fake", "M1")
        assert m is None

    def test_complete_milestone(self, assistant):
        assistant.create_project("Test")
        assistant.add_milestone("Test", "M1")
        result = assistant.complete_milestone("Test", "M1")
        assert result is True

        project = assistant.get_project("Test")
        assert project.milestones[0].completed is True
        assert project.milestones[0].completed_at != ""

    def test_create_checkpoint(self, assistant):
        assistant.create_project("Test")
        cp = assistant.create_checkpoint(
            "Test",
            "Before refactor",
            {"main.py": "abc123", "config.json": "def456"},
        )
        assert cp is not None
        assert cp.description == "Before refactor"
        assert len(cp.file_snapshot) == 2

    def test_list_checkpoints(self, assistant):
        assistant.create_project("Test")
        assistant.create_checkpoint("Test", "Checkpoint 1")
        assistant.create_checkpoint("Test", "Checkpoint 2")

        cps = assistant.list_checkpoints("Test")
        assert len(cps) == 2

    def test_get_dashboard(self, assistant):
        assistant.create_project("Active 1")
        assistant.create_project("Active 2")
        assistant.update_status("Active 2", "completed")

        dashboard = assistant.get_dashboard()
        assert dashboard["projects_total"] == 2
        assert dashboard["projects_active"] >= 1
        assert dashboard["projects_completed"] >= 1

    def test_get_project_summary(self, assistant):
        assistant.create_project("Test", "A test project")
        assistant.add_milestone("Test", "M1")
        assistant.add_milestone("Test", "M2")
        assistant.complete_milestone("Test", "M1")

        summary = assistant.get_project_summary("Test")
        assert summary is not None
        assert summary["name"] == "Test"
        assert summary["milestones_progress"] == "1/2"
        assert summary["milestones_progress_pct"] == 50.0

    def test_persistence(self, assistant):
        assistant.create_project("Test", "Description")
        assistant.add_milestone("Test", "Milestone 1")

        ws = assistant._workspace
        assistant2 = ProjectAssistant(workspace=ws)
        p = assistant2.get_project("Test")
        assert p is not None
        assert len(p.milestones) == 1


class TestCreateProjectAssistant:
    def test_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = create_project_assistant(tmp)
            assert isinstance(a, ProjectAssistant)
