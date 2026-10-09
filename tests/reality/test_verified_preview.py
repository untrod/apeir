"""Real Runtime demo acceptance: never infer effects from printed success."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nous_runtime.governance import AuthorizationContext
from nous_runtime.governance.cli import _build_context
from nous_runtime.reality.preview import run_verified_demo

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "scenario,work_state,verdict,effects",
    [
        ("match", "COMMITTED", "MATCH", 1),
        ("deny", "CREATED", None, 0),
        ("mismatch", "VERIFIED", "MISMATCH", 1),
        ("unknown", "VERIFIED", "UNKNOWN", 1),
        ("lost-response", "COMMITTED", "MATCH", 1),
        ("restart", "COMMITTED", "MATCH", 1),
    ],
)
def test_real_demo_paths(tmp_path, scenario, work_state, verdict, effects):
    result = run_verified_demo(
        tmp_path, scenario=scenario, approval_context=_build_context()
    )
    work = result["work"]
    assert work["state"] == work_state
    assert result["effect_verification"].get("verdict") == verdict
    assert result["effect_count"] == effects
    assert result["execution_scope"] == "runtime-service" and result["simulated"]
    assert result["kernel_traversed"] is False
    assert result["artifact_integrity_checked"] >= 1
    assert (
        work["provenance"]["agent_session_id"] == result["agent_session"]["session_id"]
    )
    assert (
        work["provenance"]["workflow_run_id"]
        == result["agent_session"]["workflow_run_id"]
    )
    assert any(w["work_id"] == work["work_id"] for w in result["operations"]["works"])
    assert result["operations"]["devices"][0]["metadata"]["simulation"] is True
    events = {r["event_type"] for r in result["operations"]["activity"]}
    assert {"approval.requested", "approval.decided"} <= events
    if effects:
        assert "execution.admitted" in events
        assert result["receipt"]["operation_id"] == work["work_id"]
        assert result["receipt"]["node_id"] == work["assigned_node"]
        observation_ids = {
            r["output"]["observation_id"] for r in result["observations"] if r["output"]
        }
        assert set(result["effect_verification"]["observation_ids"]) <= observation_ids
        assert len(result["observations"]) == 2
    else:
        assert result["receipt"] is None
        assert "execution.admitted" not in {
            r["event_type"]
            for r in result["operations"]["activity"]
            if r["evidence"].get("work_id") == work["work_id"]
        }
    if scenario == "lost-response":
        before = result["before_recovery"]
        assert before["effect_count"] == 1
        assert before["work"]["state"] != "COMMITTED"
        assert before["receipt"] is None
        assert (
            before["agent_session"]["plan_history"]
            == result["agent_session"]["plan_history"]
        )
        assert (
            before["agent_session"]["workflow_run_id"]
            == result["agent_session"]["workflow_run_id"]
        )


def test_no_approval_is_no_mutation(tmp_path):
    result = run_verified_demo(tmp_path)
    assert result["agent_session"]["state"] == "WAITING"
    assert result["agent_session"]["pending_approvals"]
    assert result["effect_count"] == 0
    assert result["work"]["state"] == "CREATED"


def test_recovery_waits_for_delayed_persisted_receipt_and_fresh_read(
    tmp_path, monkeypatch
):
    from nous_runtime.node_runtime.relay import NodeRelayClient

    send = NodeRelayClient._send
    delayed = []

    async def hold_evidence(self, websocket, message_type, payload, **kwargs):
        work_id = str(payload.get("workload_id", ""))
        if message_type == "WORKLOAD_STATUS" and (
            work_id == "preview-firmware-update" or work_id.startswith("observe_")
        ):
            delayed.append(work_id)
            await asyncio.sleep(1.25)
        return await send(self, websocket, message_type, payload, **kwargs)

    monkeypatch.setattr(NodeRelayClient, "_send", hold_evidence)
    result = run_verified_demo(
        tmp_path, scenario="lost-response", approval_context=_build_context()
    )
    assert "preview-firmware-update" in delayed
    assert result["work"]["state"] == "COMMITTED"
    assert any(item.startswith("observe_") for item in delayed)
    assert result["effect_verification"]["verdict"] == "MATCH"
    assert result["effect_count"] == result["before_recovery"]["effect_count"] == 1


@pytest.mark.parametrize("subject", ["agent", "model", "node", "provider", "scheduler"])
def test_caller_cannot_self_approve(tmp_path, subject):
    context = AuthorizationContext(
        subject_type=subject, subject_id="untrusted", authn_method="cli_os_user"
    )
    with pytest.raises(PermissionError):
        run_verified_demo(tmp_path, approval_context=context)
    result = run_verified_demo(tmp_path, phase="resume")
    assert result["effect_count"] == 0 and result["work"]["state"] == "CREATED"


def test_start_cannot_replace_original_state(tmp_path):
    first = run_verified_demo(tmp_path)
    with pytest.raises(ValueError, match="empty dedicated"):
        run_verified_demo(tmp_path, approval_context=_build_context())
    restored = run_verified_demo(tmp_path, phase="resume")
    assert restored["work"] == first["work"]
    assert restored["effect_count"] == 0


def test_restart_across_cli_processes_resumes_original_plan(tmp_path):
    root = tmp_path / "persisted-demo"
    env = os.environ.copy()
    checkout = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(checkout)
    cmd = [
        sys.executable,
        "-m",
        "nous_runtime",
        "demo",
        "--workspace",
        str(root),
        "--json",
    ]
    before = subprocess.run(
        cmd + ["--phase", "prepare"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    after = subprocess.run(
        cmd + ["--phase", "resume", "--approve-once"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    first, last = json.loads(before.stdout), json.loads(after.stdout)
    assert first["effect_count"] == 0
    assert last["effect_count"] == 1 and last["work"]["state"] == "COMMITTED"
    assert (
        first["agent_session"]["plan_history"] == last["agent_session"]["plan_history"]
    )
    assert first["work"]["work_id"] == last["work"]["work_id"]
    assert (
        first["agent_session"]["workflow_run_id"]
        == last["agent_session"]["workflow_run_id"]
    )
