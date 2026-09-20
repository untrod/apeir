from nous_runtime.context import ExecutionContextBuilder
from nous_runtime.intelligence.routing import route_capabilities
from nous_runtime.intelligence.task import TaskAnalyzer
from nous_runtime.task import TaskManager, TaskStatus


def test_task_to_adaptive_route_to_execution_context() -> None:
    manager = TaskManager()
    task = manager.create("Implement Python parser", "Include unit tests")
    original_status = task.status

    analysis = TaskAnalyzer().analyze(task)
    decision = route_capabilities(analysis, mode="adaptive")
    context = ExecutionContextBuilder().build(
        task,
        routing_decision=decision,
    )

    assert original_status is TaskStatus.CREATED
    assert manager.require(task.id).status is TaskStatus.CREATED
    assert context.task_id == task.id
    assert context.metadata["routing_decision"]["selected_model_id"]
    assert context.metadata["routing_decision"]["strategy"]
