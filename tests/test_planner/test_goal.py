# -*- coding: utf-8 -*-
"""Planner Goal model tests."""

from nous_runtime.planner.goal import Goal, GoalStatus


class TestGoal:
    def test_create_goal(self):
        g = Goal("Analyze project")
        assert g.objective == "Analyze project"
        assert g.goal_id.startswith("goal_")
        assert g.status == GoalStatus.CREATED

    def test_goal_lifecycle(self):
        g = Goal("Test")
        g.start_understanding()
        assert g.status == GoalStatus.UNDERSTANDING
        g.start_planning()
        assert g.status == GoalStatus.PLANNING
        g.start_executing()
        assert g.status == GoalStatus.EXECUTING
        g.complete()
        assert g.status == GoalStatus.COMPLETED

    def test_goal_failure(self):
        g = Goal("Test")
        g.fail("Something broke")
        assert g.status == GoalStatus.FAILED
        assert g.metadata["failure_reason"] == "Something broke"

    def test_goal_cancel(self):
        g = Goal("Test")
        g.cancel()
        assert g.status == GoalStatus.CANCELLED

    def test_goal_to_dict(self):
        g = Goal("Test", constraints={"max_steps": 5})
        d = g.to_dict()
        assert d["objective"] == "Test"
        assert d["constraints"]["max_steps"] == 5

    def test_long_lived_goal_round_trip_and_steering(self):
        g = Goal("Fix API", completion_criteria=["tests pass"])
        g.start_executing()
        g.steer("Do not change storage", constraints={"scope": "api"})
        g.bind_plan_revision(2)
        g.wait_for_user("need fixture")

        restored = Goal.from_dict(g.to_dict())

        assert restored.status == GoalStatus.WAITING_USER
        assert restored.requirements == ["Do not change storage"]
        assert restored.completion_criteria == ["tests pass"]
        assert restored.current_plan_revision == 2
        assert restored.blocker == "need fixture"
        restored.resume()
        assert restored.status == GoalStatus.UNDERSTANDING
