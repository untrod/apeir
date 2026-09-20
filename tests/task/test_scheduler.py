"""Priority queue and Worker tests."""

import pytest

from nous_runtime.scheduler import Priority, TaskQueue, Worker
from nous_runtime.task import Task, TaskRuntimeError, TaskStatus


def test_scheduler_orders_high_normal_low_and_preserves_fifo():
    queue = TaskQueue()
    low = queue.enqueue(Task(name="Background index", priority=Priority.LOW))
    normal = queue.enqueue(Task(name="Report", priority=Priority.NORMAL))
    high_first = queue.enqueue(Task(name="Incident A", priority=Priority.HIGH))
    high_second = queue.enqueue(Task(name="Incident B", priority=Priority.HIGH))

    assert [queue.dequeue(), queue.dequeue(), queue.dequeue(), queue.dequeue()] == [
        high_first,
        high_second,
        normal,
        low,
    ]
    assert queue.dequeue() is None


def test_scheduler_rejects_duplicates_and_terminal_tasks():
    queue = TaskQueue()
    task = queue.enqueue(Task(name="Queued"))

    with pytest.raises(TaskRuntimeError, match="already queued"):
        queue.enqueue(task)

    completed = Task(name="Completed")
    completed.transition(TaskStatus.PLANNED)
    completed.transition(TaskStatus.RUNNING)
    completed.transition(TaskStatus.COMPLETED)
    with pytest.raises(TaskRuntimeError, match="terminal task"):
        TaskQueue().enqueue(completed)


def test_worker_executes_task_to_completion():
    queue = TaskQueue()
    task = queue.enqueue(Task(name="Execute"))

    result = Worker(lambda current: {"task_id": current.id}).run_next(queue)

    assert result.ok is True
    assert result.task is task
    assert result.value == {"task_id": task.id}
    assert task.status is TaskStatus.COMPLETED


def test_worker_records_failure_without_agent_dependency():
    queue = TaskQueue()
    task = queue.enqueue(Task(name="Fail"))

    def fail(_task):
        raise RuntimeError("worker failed")

    result = Worker(fail).run_next(queue)

    assert result.ok is False
    assert result.error == "worker failed"
    assert task.status is TaskStatus.FAILED
