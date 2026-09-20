"""In-memory checkpoint framework tests."""

from nous_runtime.checkpoint import Checkpoint, InMemoryCheckpointStore


def test_checkpoint_store_saves_and_loads_state():
    store = InMemoryCheckpointStore()
    checkpoint = Checkpoint(
        task_id="task-1",
        state={"step": 3, "status": "WAITING"},
        metadata={"reason": "approval"},
    )

    assert store.save(checkpoint) is checkpoint
    assert store.load(checkpoint.checkpoint_id) is checkpoint
    assert store.load("missing") is None


def test_checkpoint_store_lists_by_task():
    store = InMemoryCheckpointStore()
    first = store.save(Checkpoint(task_id="task-1", state={"step": 1}))
    second = store.save(Checkpoint(task_id="task-2", state={"step": 1}))

    assert store.list("task-1") == [first]
    assert {item.checkpoint_id for item in store.list()} == {
        first.checkpoint_id,
        second.checkpoint_id,
    }


def test_checkpoint_round_trip_detaches_state():
    checkpoint = Checkpoint(task_id="task-1", state={"items": [1, 2]})

    restored = Checkpoint.from_dict(checkpoint.to_dict())

    assert restored.to_dict() == checkpoint.to_dict()
    assert restored.state is not checkpoint.state
