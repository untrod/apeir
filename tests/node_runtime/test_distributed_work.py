from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nous_runtime.node_runtime.distributed_work import (
    DistributedWork,
    DistributedWorkError,
    DistributedWorkState,
    DistributedWorkStore,
    WorkExecutionPolicy,
    WorkRequirements,
)
from nous_runtime.node_runtime.relay_cli import app


def test_distributed_work_round_trip_and_state_machine(tmp_path: Path):
    store = DistributedWorkStore(tmp_path / "controller")
    created = store.create(
        DistributedWork(
            work_id="work-vision-1",
            intent="Run computer vision inference",
            creator="acceptance",
            priority=25,
            requirements=WorkRequirements(
                architectures=("AARCH64",),
                operating_systems=("Linux",),
                capabilities=("CUDA", "system.echo"),
                minimum_memory_bytes=8 * 1024**3,
                gpu_required=True,
            ),
            input_artifacts=("artifact://sha256/input",),
            execution_policy=WorkExecutionPolicy(),
        )
    )

    assert created.state is DistributedWorkState.CREATED
    assert created.requirements.architectures == ("arm64",)
    assert created.requirements.operating_systems == ("linux",)
    assert created.execution_policy.delivery == "at_most_once"
    scheduled = store.transition(
        created.work_id,
        DistributedWorkState.SCHEDULED,
        reason="requirements accepted",
    )
    assigned = store.transition(
        scheduled.work_id,
        DistributedWorkState.ASSIGNED,
        reason="deterministic placement",
        assigned_node="node-jetson",
    )
    running = store.transition(
        assigned.work_id,
        DistributedWorkState.RUNNING,
        reason="signed start acknowledged",
    )

    reopened = DistributedWorkStore(tmp_path / "controller")
    persisted = reopened.get(running.work_id)
    assert persisted is not None
    assert persisted.state is DistributedWorkState.RUNNING
    assert persisted.assigned_node == "node-jetson"
    assert len(persisted.state_history) == 4
    assert reopened.counts() == {"RUNNING": 1}


def test_distributed_work_rejects_invalid_transitions_and_artifacts(tmp_path: Path):
    store = DistributedWorkStore(tmp_path)
    work = store.create(DistributedWork(intent="verify state machine"))

    with pytest.raises(DistributedWorkError, match="CREATED -> RUNNING"):
        store.transition(
            work.work_id,
            DistributedWorkState.RUNNING,
            reason="skip placement",
            assigned_node="node-a",
        )
    with pytest.raises(DistributedWorkError, match="reason is required"):
        store.transition(
            work.work_id,
            DistributedWorkState.SCHEDULED,
            reason="",
        )
    with pytest.raises(DistributedWorkError, match="artifact://"):
        DistributedWork(intent="invalid artifact", input_artifacts=("input.bin",))


def test_controller_cli_submits_and_reads_durable_work(tmp_path: Path):
    state = tmp_path / "controller"
    runner = CliRunner()
    submitted = runner.invoke(
        app,
        [
            "submit-work",
            "--state-dir",
            str(state),
            "--work-id",
            "work-cli-1",
            "--intent",
            "Run inference",
            "--architecture",
            "aarch64",
            "--capability",
            "cuda",
            "--os",
            "linux",
            "--minimum-memory-bytes",
            str(8 * 1024**3),
            "--gpu-required",
            "--input-artifact",
            "artifact://sha256/dataset",
            "--creator",
            "operator",
        ],
    )
    assert submitted.exit_code == 0, submitted.output
    value = json.loads(submitted.stdout)
    assert value["schema"] == "apeir.compute-mesh-work/v1"
    assert value["state"] == "CREATED"
    assert value["requirements"]["architectures"] == ["arm64"]
    assert value["requirements"]["operating_systems"] == ["linux"]

    status = runner.invoke(
        app,
        ["work-status", "work-cli-1", "--state-dir", str(state)],
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)["intent"] == "Run inference"

    listing = runner.invoke(app, ["work-status", "--state-dir", str(state)])
    assert listing.exit_code == 0, listing.output
    assert json.loads(listing.stdout)["counts"] == {"CREATED": 1}


@pytest.mark.parametrize("read", ["get", "list", "counts", "restart"])
def test_work_readers_share_writer_lock_and_observe_complete_transition(
    tmp_path, monkeypatch, read
):
    """A reader cannot replace the writer's working snapshot during admission."""
    from concurrent.futures import ThreadPoolExecutor
    import threading

    store = DistributedWorkStore(tmp_path)
    work = store.create(DistributedWork(intent="serialize canonical state"))
    writing = threading.Event()
    release = threading.Event()
    reading = threading.Event()
    loaded = threading.Event()
    original_save = store._save
    original_load = DistributedWorkStore._load

    def save(works):
        writing.set()
        if not release.wait(5):
            raise RuntimeError("test writer did not release")
        return original_save(works)

    def load(current):
        if reading.is_set():
            loaded.set()
        return original_load(current)

    monkeypatch.setattr(store, "_save", save)
    monkeypatch.setattr(DistributedWorkStore, "_load", load)

    def inspect():
        reading.set()
        if read == "restart":
            return DistributedWorkStore(tmp_path).get(work.work_id)
        return (
            getattr(store, read)(work.work_id)
            if read == "get"
            else getattr(store, read)()
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(
            store.transition,
            work.work_id,
            DistributedWorkState.SCHEDULED,
            reason="serialized transition",
        )
        try:
            assert writing.wait(5)
            reader = pool.submit(inspect)
            assert reading.wait(5)
            assert not loaded.wait(0.1), "reader entered the store during a write"
            release.set()
            assert writer.result(timeout=5).state is DistributedWorkState.SCHEDULED
            observed = reader.result(timeout=5)
        finally:
            release.set()
    if read in {"get", "restart"}:
        assert observed.state is DistributedWorkState.SCHEDULED
    elif read == "list":
        assert observed[0].state is DistributedWorkState.SCHEDULED
    else:
        assert observed == {"SCHEDULED": 1}
    assert (
        DistributedWorkStore(tmp_path).get(work.work_id).state
        is DistributedWorkState.SCHEDULED
    )
