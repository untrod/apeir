"""Original Work submission survives retries without another execution owner."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import http.client
import json
import threading

import pytest

from nous_runtime.api.server import create_server
from nous_runtime.checkpoint import Checkpoint
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.work import (
    DecisionStatus,
    WorkDecision,
    WorkExecutionComponents,
    WorkSupervisor,
)
from nous_runtime.work.runtime import WorkHarness


def components(calls):
    def deliberate(context):
        calls.append(context.run_id)
        return WorkDecision(DecisionStatus.COMPLETE, "Bounded result", output="done")

    return lambda *_: WorkExecutionComponents(
        tools=None, deliberator=deliberate, verifier=None
    )


@contextmanager
def server_for(root, supervisor, monkeypatch):
    root.mkdir(exist_ok=True)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.work.submission.service")
    monkeypatch.setenv("NOUS_API_SUBJECT", "submission-service")
    monkeypatch.setattr("nous_runtime.work.get_work_supervisor", lambda *_: supervisor)
    gate = ExecutionAuthorizationGate(GovernanceStore(root / ".nous"))
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", gate)
    monkeypatch.setattr(
        "nous_runtime.governance.broker._broker", ApprovalBroker(gate.store)
    )
    server = create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    def send(body, token):
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        try:
            connection.request(
                "POST",
                "/api/v1/work",
                json.dumps(body),
                {
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            return json.loads(response.read())
        finally:
            connection.close()

    approvals = []

    def post(body, token="fake.work.submission.service"):
        result = send(body, token)
        if result.get("error", {}).get("code") == "NOUS_APPROVAL_REQUIRED":
            # This owned fixture explicitly approves each submission using the
            # existing trusted local-human boundary. The service never approves
            # itself, and HTTP admission/one-use lease consumption remain real.
            request_id = result["error"]["details"]["approval_request_id"]
            approvals.append(request_id)
            ApprovalBroker(gate.store).respond_legacy(
                request_id, "approve", _build_context(), gate=gate
            )
            result = send(body, token)
        return result

    post.approvals = approvals
    post.send = send
    try:
        yield post
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        supervisor.close()
        assert not thread.is_alive()


def test_http_lost_response_reuses_original_work_and_deliberation(
    tmp_path, monkeypatch
):
    calls = []
    supervisor = WorkSupervisor(tmp_path, component_factory=components(calls))
    body = {
        "objective": "Explain the original bounded result",
        "read_only": True,
        "idempotency_key": "original-submit-1",
    }
    with server_for(tmp_path, supervisor, monkeypatch) as post:
        original = post(body)
        assert original["ok"], original
        work = original["data"]["work"]
        supervisor.wait(work["run_id"], timeout=5)
        # The caller lost its first response. The exact original submission
        # must remain a read of that Run, not another model or tool invocation.
        repeated = post(body)
        assert repeated["ok"], repeated
        assert repeated["data"]["work"]["run_id"] == work["run_id"]
        assert calls == [work["run_id"]]
        assert len(WorkHarness(tmp_path).list()) == 1
        assert len(post.approvals) == 1


def test_submission_response_does_not_reinspect_execution_history(
    tmp_path, monkeypatch
):
    calls, inspections = [], []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))

    def unavailable_history(self, run_id):
        inspections.append(run_id)
        raise OSError("controlled execution history read failure")

    monkeypatch.setattr(WorkHarness, "inspect", unavailable_history)
    body = {
        "objective": "Return the original admitted Work without replaying it",
        "read_only": True,
        "idempotency_key": "accepted-without-history-read",
    }
    with server_for(tmp_path, host, monkeypatch) as post:
        accepted = post(body)
        assert accepted["ok"], accepted
        run_id = accepted["data"]["work"]["run_id"]
        assert accepted["data"]["supervisor"]["worker_known"] is True
        host.wait(run_id, timeout=5)
        repeated = post(body)
        assert repeated["ok"], repeated
        assert repeated["data"]["work"]["run_id"] == run_id
        assert repeated["data"]["supervisor"]["worker_done"] is True
        assert calls == [run_id]
        assert len(post.approvals) == 1
        assert inspections == []
        # Inspection remains an explicit canonical read, and still surfaces its
        # failure. The submission receipt does not invent available evidence.
        with pytest.raises(OSError, match="execution history read failure"):
            host.inspect(run_id)
        assert inspections == [run_id]


def test_concurrent_supervisors_and_restart_do_not_resubmit(tmp_path):
    calls = []
    supervisors = [
        WorkSupervisor(tmp_path, component_factory=components(calls)) for _ in range(2)
    ]
    arguments = dict(submission_key="same", submission_actor="service:caller")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda host: host.start("One original result", **arguments),
                    supervisors,
                )
            )
        assert results[0].run_id == results[1].run_id
        for host in supervisors:
            host.wait(results[0].run_id, timeout=5)
    finally:
        for host in supervisors:
            host.close()
    restarted = WorkSupervisor(tmp_path, component_factory=components(calls))
    try:
        repeated = restarted.start("One original result", **arguments)
        assert repeated.run_id == results[0].run_id
        assert not restarted.is_active(repeated.run_id)
        assert calls == [repeated.run_id]
    finally:
        restarted.close()


@pytest.mark.parametrize(
    "change", ["objective", "read_only", "constraints", "preferred_model"]
)
def test_changed_request_cannot_reuse_original_submission(tmp_path, change):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    original = dict(objective="Explain a result", read_only=True)
    key = dict(submission_key="same", submission_actor="service:caller")
    try:
        first = host.start(**original, **key)
        host.wait(first.run_id, timeout=5)
        changed = {
            **original,
            change: {"different": True}
            if change == "constraints"
            else False
            if change == "read_only"
            else "different",
        }
        with pytest.raises(ValueError, match="submission binding"):
            host.start(**changed, **key)
        assert calls == [first.run_id]
    finally:
        host.close()


def test_initialization_failure_fences_repeated_request(tmp_path, monkeypatch):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    original = WorkHarness.create

    def interrupted(*args, **kwargs):
        raise OSError("controlled initialization interruption")

    monkeypatch.setattr(WorkHarness, "create", interrupted)
    arguments = dict(submission_key="incomplete", submission_actor="service:caller")
    try:
        with pytest.raises(OSError, match="controlled"):
            host.start("An original request", **arguments)
        monkeypatch.setattr(WorkHarness, "create", original)
        with pytest.raises(RuntimeError, match="submission initialization.*UNKNOWN"):
            host.start("An original request", **arguments)
        assert not calls
        assert WorkHarness(tmp_path).list() == []
    finally:
        host.close()


def test_changed_checkpoint_binding_cannot_start_another_execution(tmp_path):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    arguments = dict(submission_key="original", submission_actor="service:caller")
    try:
        original = host.start("Explain a result", **arguments)
        host.wait(original.run_id, timeout=5)
        store = WorkHarness(tmp_path).checkpoints
        record = next(
            row for row in store.list() if row.metadata.get("kind") == "work_submission"
        )
        store.save(
            Checkpoint(
                checkpoint_id=record.checkpoint_id,
                task_id=record.task_id,
                state={**record.state, "input_sha256": "0" * 64},
                metadata=record.metadata,
            )
        )
        with pytest.raises(ValueError, match="submission binding"):
            host.start("Explain a result", **arguments)
        assert calls == [original.run_id]
    finally:
        host.close()


def test_normal_checkpoint_pruning_preserves_original_submission(tmp_path):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    arguments = dict(submission_key="original", submission_actor="service:caller")
    try:
        original = host.start("Explain a result", **arguments)
        host.wait(original.run_id, timeout=5)
        store = WorkHarness(tmp_path).checkpoints
        plan = store.inspect(keep_latest_per_task=1)["retention"]
        store.prune(keep_latest_per_task=1, expected_plan_digest=plan["plan_digest"])
        assert host.start("Explain a result", **arguments).run_id == original.run_id
        assert calls == [original.run_id]
    finally:
        host.close()


def test_http_caller_claims_and_invalid_auth_cannot_select_submission_identity(
    tmp_path, monkeypatch
):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    body = {
        "objective": "Explain identity",
        "idempotency_key": "original",
        "submission_actor": "human:owner",
    }
    with server_for(tmp_path, host, monkeypatch) as post:
        assert not post(body, token="wrong")["ok"]
        assert not calls
        accepted = post(body)
        assert accepted["ok"], accepted
        host.wait(accepted["data"]["work"]["run_id"], timeout=5)
        records = [
            row
            for row in WorkHarness(tmp_path).checkpoints.list()
            if row.metadata.get("kind") == "work_submission"
        ]
        assert len(records) == 1
        assert "human:owner" not in json.dumps(records[0].to_dict())
        assert "fake.work.submission.service" not in json.dumps(records[0].to_dict())


def test_lookup_missing_key_does_not_create_or_dispatch_work(tmp_path):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    try:
        assert (
            host.find_submission(
                "No new work",
                submission_key="absent",
                submission_actor="service:caller",
            )
            is None
        )
        assert not calls
        assert WorkHarness(tmp_path).list() == []
    finally:
        host.close()


def test_same_key_different_authenticated_actor_is_separate_work(tmp_path):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    try:
        first = host.start(
            "Original", submission_key="same", submission_actor="service:first"
        )
        second = host.start(
            "Original", submission_key="same", submission_actor="service:second"
        )
        host.wait(first.run_id, timeout=5)
        host.wait(second.run_id, timeout=5)
        assert first.run_id != second.run_id
        assert sorted(calls) == sorted([first.run_id, second.run_id])
    finally:
        host.close()


def test_two_runtime_processes_keep_one_original_submission(tmp_path):
    import subprocess
    import sys

    script = r"""
import sys
from pathlib import Path
from nous_runtime.work import WorkSupervisor, WorkExecutionComponents, WorkDecision, DecisionStatus
root = Path(sys.argv[1])
def deliberate(context):
    with (root / "calls.txt").open("a") as output:
        output.write(context.run_id + "\n")
    return WorkDecision(DecisionStatus.COMPLETE, "Original result", output="done")
input()
host = WorkSupervisor(root, component_factory=lambda *_: WorkExecutionComponents(None, deliberate, None))
try:
    work = host.start("One admitted request", submission_key="same", submission_actor="service:caller")
    host.wait(work.run_id, timeout=5)
    print(work.run_id, flush=True)
finally:
    host.close()
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.stdin.write("start\n")
            process.stdin.flush()
        results = [process.communicate(timeout=20) for process in processes]
        assert all(process.returncode == 0 for process in processes), results
        runs = [stdout.strip() for stdout, _ in results]
        assert runs[0] == runs[1]
        assert (tmp_path / "calls.txt").read_text().splitlines() == [runs[0]]
        assert len(WorkHarness(tmp_path).list()) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("key", ["", "x" * 129, "../outside", None])
def test_invalid_original_submission_is_rejected_before_approval(
    tmp_path, monkeypatch, key
):
    calls = []
    host = WorkSupervisor(tmp_path, component_factory=components(calls))
    with server_for(tmp_path, host, monkeypatch) as post:
        response = post({"objective": "Read original state", "idempotency_key": key})
        assert (
            not response["ok"] and response["error"]["code"] == "NOUS_INVALID_REQUEST"
        )
        assert post.approvals == []
        assert not calls
