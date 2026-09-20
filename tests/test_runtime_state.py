"""RuntimeState foundation contract tests."""

import pytest

from nous_runtime.core.errors import RuntimeStateError
from nous_runtime.core.state import RUNTIME_STATE_DOMAINS, RuntimeState


def test_runtime_state_creates_all_foundation_domains():
    state = RuntimeState()

    assert RUNTIME_STATE_DOMAINS == (
        "tasks",
        "providers",
        "decisions",
        "memory",
        "artifacts",
    )
    assert all(getattr(state, domain) == {} for domain in RUNTIME_STATE_DOMAINS)


def test_runtime_state_registers_queries_and_removes_values():
    state = RuntimeState()
    task = {"status": "created"}

    assert state.register("tasks", "task-1", task) is task
    assert state.get("tasks", "task-1") is task
    assert state.remove("tasks", "task-1") is task
    assert state.get("tasks", "task-1") is None
    assert state.remove("tasks", "missing") is None


def test_runtime_state_domains_are_isolated():
    state = RuntimeState()
    state.register("tasks", "shared", "task")
    state.register("artifacts", "shared", "artifact")

    assert state.get("tasks", "shared") == "task"
    assert state.get("artifacts", "shared") == "artifact"


def test_runtime_state_rejects_unknown_domains_and_empty_keys():
    state = RuntimeState()

    with pytest.raises(RuntimeStateError, match="unknown Runtime state domain"):
        state.register("agents", "agent-1", {})
    with pytest.raises(RuntimeStateError, match="key is required"):
        state.get("tasks", "")
