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
