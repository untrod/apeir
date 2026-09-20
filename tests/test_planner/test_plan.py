# -*- coding: utf-8 -*-
"""Planner Plan + Task Graph tests."""

from nous_runtime.planner.plan import Plan, TaskStatus
from nous_runtime.planner.graph import TaskGraph


class TestPlan:
    def test_create_plan(self):
        plan = Plan(goal_id="goal_001")
        assert plan.plan_id.startswith("plan_")
        assert len(plan.tasks) == 0

    def test_add_task(self):
        plan = Plan(goal_id="goal_001")
        task = plan.add_task("Step 1", capability_id="test.action")
        assert task.description == "Step 1"
        assert task.capability_id == "test.action"
        assert len(plan.tasks) == 1

    def test_progress(self):
        plan = Plan(goal_id="goal_001")
        t1 = plan.add_task("A", capability_id="test.a")
        plan.add_task("B", capability_id="test.b")
        t1.status = TaskStatus.COMPLETED
        p = plan.progress()
        assert p["total"] == 2
        assert p["done"] == 1
        assert p["pending"] == 1

    def test_all_done(self):
        plan = Plan(goal_id="goal_001")
        t = plan.add_task("A", capability_id="test.a")
        t.status = TaskStatus.COMPLETED
        assert plan.all_done()


class TestTaskGraph:
    def test_sequential(self):
        plan = Plan(goal_id="goal_001")
        a = plan.add_task("A", capability_id="test.a")
        b = plan.add_task("B", capability_id="test.b", depends_on=[a.task_id])

        graph = TaskGraph()
        roots = graph.build(plan.tasks)
        assert len(roots) == 1
        assert roots[0].task_id == a.task_id
        assert len(roots[0].children) == 1
        assert roots[0].children[0].task_id == b.task_id

    def test_parallel(self):
        plan = Plan(goal_id="goal_001")
        a = plan.add_task("A", capability_id="test.a")
        b = plan.add_task("B", capability_id="test.b")
        plan.add_task("C", capability_id="test.c", depends_on=[a.task_id, b.task_id])

        graph = TaskGraph()
        roots = graph.build(plan.tasks)
        assert len(roots) == 2  # A and B are independent

    def test_level_order(self):
        plan = Plan(goal_id="goal_001")
        a = plan.add_task("A", capability_id="test.a")
        b = plan.add_task("B", capability_id="test.b", depends_on=[a.task_id])
        plan.add_task("C", capability_id="test.c", depends_on=[b.task_id])

        graph = TaskGraph()
        graph.build(plan.tasks)
        levels = graph.level_order()
        assert len(levels) == 3  # 3 levels deep

    def test_ready_nodes(self):
        plan = Plan(goal_id="goal_001")
        a = plan.add_task("A", capability_id="test.a")
        plan.add_task("B", capability_id="test.b", depends_on=[a.task_id])

        graph = TaskGraph()
        graph.build(plan.tasks)
        ready = graph.ready_nodes(set())
        assert len(ready) == 1
        assert ready[0].task_id == a.task_id

    def test_to_mermaid(self):
        plan = Plan(goal_id="goal_001")
        plan.add_task("A", capability_id="test.a")
        graph = TaskGraph()
        graph.build(plan.tasks)
        mermaid = graph.to_mermaid()
        assert "graph TD" in mermaid
