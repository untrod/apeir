from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from nous_runtime.agent.checkpoint import AgentCheckpointManager
from nous_runtime.agent.execution_state import AgentExecutionState, InvocationStatus
from nous_runtime.agent.runtime import AgentExecutionRuntime
from nous_runtime.agent.termination import TerminationPolicy
from nous_runtime.checkpoint import (
    Checkpoint,
    CheckpointStoreError,
    SQLiteCheckpointStore,
)
from nous_runtime.core.redaction import REDACTED
from nous_runtime.model_runtime.bridges import GatewayChatHandler


def test_sqlite_checkpoint_store_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "agent-checkpoints.db"
    first_store = SQLiteCheckpointStore(path)
    first = first_store.save(Checkpoint(task_id="task-1", state={"step": 1}))
    second = first_store.save(Checkpoint(task_id="task-2", state={"step": 2}))

    restarted_store = SQLiteCheckpointStore(path)

    assert restarted_store.load(first.checkpoint_id) == first
    assert restarted_store.list("task-1") == [first]
    assert {item.checkpoint_id for item in restarted_store.list()} == {
        first.checkpoint_id,
        second.checkpoint_id,
    }


def test_sqlite_checkpoint_store_fails_closed_on_tampering(tmp_path) -> None:
    path = tmp_path / "agent-checkpoints.db"
    store = SQLiteCheckpointStore(path)
    checkpoint = store.save(Checkpoint(task_id="task-1", state={"step": 1}))
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE checkpoints SET payload_json = ? WHERE checkpoint_id = ?",
            ('{"state":{"step":99}}', checkpoint.checkpoint_id),
        )
        connection.commit()

    with pytest.raises(CheckpointStoreError, match="integrity"):
        SQLiteCheckpointStore(path).load(checkpoint.checkpoint_id)


def test_agent_runtime_restores_budget_from_durable_checkpoint(
    tmp_path, agent_profile
) -> None:
    path = tmp_path / "agent-checkpoints.db"
    first_runtime = AgentExecutionRuntime(
        checkpoints=AgentCheckpointManager(SQLiteCheckpointStore(path))
    )
    execution = first_runtime.create(task_id="task-p8", profile=agent_profile)
    first_runtime.start(execution.run_id)
    invocation = first_runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        handler=lambda request: "ok",
    )
    checkpoint = first_runtime.checkpoint(execution.run_id)

    assert invocation.status is InvocationStatus.COMPLETED
    assert first_runtime.require(execution.run_id).state is (
        AgentExecutionState.CHECKPOINTED
    )

    restarted_runtime = AgentExecutionRuntime(
        checkpoints=AgentCheckpointManager(SQLiteCheckpointStore(path))
    )
    restored = restarted_runtime.restore(
        checkpoint.checkpoint_id,
        profile=agent_profile,
    )

    assert restored.run_id == execution.run_id
    assert restored.state is AgentExecutionState.CHECKPOINTED
    assert restarted_runtime.budget_for(restored.run_id).usage.tool_invocations == 1


def test_agent_checkpoint_redacts_handler_secret_before_persistence(
    tmp_path, agent_profile
) -> None:
    path = tmp_path / "agent-checkpoints.db"
    manager = AgentCheckpointManager(SQLiteCheckpointStore(path))
    runtime = AgentExecutionRuntime(checkpoints=manager)
    execution = runtime.create(task_id="task-secret", profile=agent_profile)
    runtime.start(execution.run_id)
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"  # security-scan: fixture

    def fail_with_secret(request):
        raise RuntimeError(f"provider rejected api_key={secret}")

    invocation = runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        handler=fail_with_secret,
    )
    checkpoint = manager.save(
        runtime.require(execution.run_id),
        runtime.budget_for(execution.run_id).usage,
        TerminationPolicy(),
    )
    with closing(sqlite3.connect(path)) as connection:
        payload = connection.execute(
            "SELECT payload_json FROM checkpoints WHERE checkpoint_id = ?",
            (checkpoint.checkpoint_id,),
        ).fetchone()[0]
    restored = AgentCheckpointManager(SQLiteCheckpointStore(path)).restore(
        checkpoint.checkpoint_id
    )

    assert invocation.status is InvocationStatus.FAILED
    assert secret not in payload
    assert REDACTED in payload
    assert restored.execution.invocations[-1].message == REDACTED


def test_gateway_handler_can_bind_workspace_durable_checkpoints(
    tmp_path,
) -> None:
    handler = GatewayChatHandler(
        object(),  # type: ignore[arg-type]
        checkpoint_root=str(tmp_path),
    )

    store = handler.agent_runtime.checkpoints.store
    assert isinstance(store, SQLiteCheckpointStore)
    assert store.path == (tmp_path / ".nous" / "agent-checkpoints.db").resolve()


def test_concurrent_checkpoint_initialization_preserves_every_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "shared-cold-checkpoints.db"
    ready = Barrier(16)

    def writer(index):
        ready.wait(timeout=5)
        store = SQLiteCheckpointStore(path)
        row = store.save(Checkpoint(task_id=f"owner-{index}", state={"owner": index}))
        assert store.load(row.checkpoint_id) == row
        return row

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(writer, range(16)))
    restored = SQLiteCheckpointStore(path)
    assert {row.checkpoint_id for row in restored.list()} == {
        row.checkpoint_id for row in rows
    }
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_checkpoint_initialization_preserves_cross_process_owners(tmp_path):
    import json
    import subprocess
    import sys

    path = tmp_path / "process-checkpoints.db"
    script = """
import json, sys
from nous_runtime.checkpoint import Checkpoint, SQLiteCheckpointStore
assert sys.stdin.readline().strip() == 'start'
store = SQLiteCheckpointStore(sys.argv[1])
row = store.save(Checkpoint(task_id=sys.argv[2], state={'owner': sys.argv[2]}))
assert store.load(row.checkpoint_id) == row
print(json.dumps({'checkpoint_id': row.checkpoint_id, 'task_id': row.task_id}))
"""
    processes = []
    try:
        for index in range(4):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", script, str(path), f"process-{index}"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        # Release independent interpreters before waiting for any one result.
        for process in processes:
            process.stdin.write("start\n")
            process.stdin.flush()
        rows = []
        for process in processes:
            output, errors = process.communicate(timeout=20)
            assert process.returncode == 0, errors
            rows.append(json.loads(output))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    restored = SQLiteCheckpointStore(path)
    assert {row.checkpoint_id for row in restored.list()} == {
        row["checkpoint_id"] for row in rows
    }
    assert {row.task_id for row in restored.list()} == {
        f"process-{index}" for index in range(4)
    }
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
