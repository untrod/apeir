# -*- coding: utf-8 -*-
"""Planner execution Observation tests."""

from nous_runtime.planner.dispatcher import Dispatcher
from nous_runtime.planner.observation import Observation
from nous_runtime.planner.pipeline import DecisionPipeline
from nous_runtime.planner.plan import Plan, TaskStatus


class TestDispatcherObservation:
    def test_dispatch_task_returns_observation(self):
        from remote_terminal.nous_core.capability import unregister_capability
        from remote_terminal.nous_core.provider import Provider, register_adapter, unregister_adapter

        class EchoProvider(Provider):
            provider_id = "planner_dispatch_test"
            provider_name = "Planner Dispatch Test"

            def list_capabilities(self):
                return ["test.planner_echo"]

            def invoke(self, capability_id, **params):
                return {"ok": True, "value": params["value"]}

            def health(self):
                return {"status": "ok"}

        provider = EchoProvider()
        register_adapter(provider)
        try:
            plan = Plan(goal_id="goal_test")
            task = plan.add_task("Echo", capability_id="test.planner_echo", value=5)

            obs = Dispatcher().dispatch_observation(task)
        finally:
            unregister_adapter(provider.provider_id)
            unregister_capability("test.planner_echo")

        assert isinstance(obs, Observation)
        assert obs.status == "success"
        assert obs.tool == "task.execute"
        assert obs.data["task_id"] == task.task_id
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"ok": True, "value": 5}
        assert task.observations

    def test_dispatch_plan_returns_plan_observation(self):
        from remote_terminal.nous_core.capability import unregister_capability
        from remote_terminal.nous_core.provider import Provider, register_adapter, unregister_adapter

        class EchoProvider(Provider):
            provider_id = "planner_plan_dispatch_test"
            provider_name = "Planner Plan Dispatch Test"

            def list_capabilities(self):
                return ["test.planner_plan_echo"]

            def invoke(self, capability_id, **params):
                return {"ok": True, "value": params["value"]}

            def health(self):
                return {"status": "ok"}

        provider = EchoProvider()
        register_adapter(provider)
        try:
            plan = Plan(goal_id="goal_test")
            a = plan.add_task("A", capability_id="test.planner_plan_echo", value=1)
            plan.add_task("B", capability_id="test.planner_plan_echo", depends_on=[a.task_id], value=2)

            obs = Dispatcher().dispatch_plan_observation(plan)
        finally:
            unregister_adapter(provider.provider_id)
            unregister_capability("test.planner_plan_echo")

        assert obs.status == "success"
        assert obs.tool == "plan.execute"
        assert obs.data["progress"]["done"] == 2
        assert len(obs.data["task_observations"]) == 2


class TestPipelineTaskConstruction:
    def test_add_tasks_unwraps_params_and_resolves_placeholders(self):
        plan = Plan(goal_id="goal_test")
        task_defs = [
            {
                "description": "A",
                "capability_id": "test.a",
                "params": {"value": 1},
            },
            {
                "description": "B",
                "capability_id": "test.b",
                "params": {"value": 2},
                "depends_on": ["task_auto_0"],
            },
        ]

        DecisionPipeline._add_tasks(plan, task_defs)

        assert plan.tasks[0].params == {"value": 1}
        assert plan.tasks[1].params == {"value": 2}
        assert plan.tasks[1].depends_on == [plan.tasks[0].task_id]
