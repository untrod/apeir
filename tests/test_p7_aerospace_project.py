from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nous_runtime.checkpoint import SQLiteCheckpointStore
from nous_runtime.events import EventStream
from nous_runtime.kernel.windows_sandbox import executable_path


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


class _ExecuteGate:
    def evaluate(self, proposal, context):
        return SimpleNamespace(
            action_mode="EXECUTE",
            reason_message="allowed",
            reason_code="TEST",
            decision_id="decision-p7",
        )


class _PauseFacade:
    def try_invoke_sync(self, request):
        from nous_runtime.model_runtime.facade import GatewayResponse

        return GatewayResponse(
            request_id=request.execution.task_id,
            content="I will continue the implementation.",
            provider_id="deterministic",
            model_id="deterministic/p7-pause",
        )


class _AerospaceFacade:
    def __init__(self) -> None:
        self.calls = 0

    def try_invoke_sync(self, request):
        from nous_runtime.model_runtime.facade import GatewayResponse

        collaboration_role = str(
            (request.metadata or {}).get("collaboration_role") or ""
        )
        if collaboration_role:
            content = (
                "APPROVED: deterministic receipts satisfy the request."
                if collaboration_role == "nous.reviewer"
                else "Deterministic implementation brief."
            )
            return GatewayResponse(
                request_id=request.execution.task_id,
                content=content,
                provider_id="deterministic",
                model_id="deterministic/p7-collaboration",
            )

        self.calls += 1
        if self.calls == 1:
            files = [
                {
                    "path": "aerospace/hohmann.py",
                    "content": _HOHMANN_SOURCE,
                },
                {
                    "path": "aerospace/test_hohmann.py",
                    "content": _HOHMANN_TEST,
                },
                {
                    "path": "aerospace/README.md",
                    "content": _README,
                },
            ]
            return GatewayResponse(
                request_id=request.execution.task_id,
                provider_id="deterministic",
                model_id="deterministic/p7",
                tool_calls=(
                    {
                        "id": "p7-write-project",
                        "type": "function",
                        "function": {
                            "name": "write_files",
                            "arguments": json.dumps({"files": files}),
                        },
                    },
                ),
            )
        if self.calls == 2:
            return GatewayResponse(
                request_id=request.execution.task_id,
                provider_id="deterministic",
                model_id="deterministic/p7",
                tool_calls=(
                    {
                        "id": "p7-run-tests",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": json.dumps(
                                {
                                    "command": [
                                        "python",
                                        "-m",
                                        "pytest",
                                        "-q",
                                        "aerospace/test_hohmann.py",
                                    ],
                                    "timeout_seconds": 60,
                                }
                            ),
                        },
                    },
                ),
            )
        return GatewayResponse(
            request_id=request.execution.task_id,
            content=(
                "The Hohmann-transfer project was created and its deterministic "
                "verification passed."
            ),
            provider_id="deterministic",
            model_id="deterministic/p7",
        )


_HOHMANN_SOURCE = '''"""Deterministic two-impulse Hohmann transfer calculations."""

from __future__ import annotations

import math

EARTH_MU_KM3_S2 = 398600.4418


def hohmann_transfer(
    initial_radius_km: float,
    final_radius_km: float,
    *,
    mu_km3_s2: float = EARTH_MU_KM3_S2,
) -> dict[str, float]:
    """Return the two burns and half-ellipse flight time in consistent units."""
    if initial_radius_km <= 0 or final_radius_km <= 0 or mu_km3_s2 <= 0:
        raise ValueError("Radii and gravitational parameter must be positive.")

    transfer_axis_km = (initial_radius_km + final_radius_km) / 2.0
    circular_initial = math.sqrt(mu_km3_s2 / initial_radius_km)
    circular_final = math.sqrt(mu_km3_s2 / final_radius_km)
    transfer_initial = math.sqrt(
        mu_km3_s2 * (2.0 / initial_radius_km - 1.0 / transfer_axis_km)
    )
    transfer_final = math.sqrt(
        mu_km3_s2 * (2.0 / final_radius_km - 1.0 / transfer_axis_km)
    )
    delta_v1 = transfer_initial - circular_initial
    delta_v2 = circular_final - transfer_final
    transfer_seconds = math.pi * math.sqrt(transfer_axis_km**3 / mu_km3_s2)
    return {
        "delta_v1_km_s": delta_v1,
        "delta_v2_km_s": delta_v2,
        "total_delta_v_km_s": abs(delta_v1) + abs(delta_v2),
        "transfer_seconds": transfer_seconds,
    }
'''


_HOHMANN_TEST = '''from __future__ import annotations

import pytest

from aerospace.hohmann import hohmann_transfer


def test_low_earth_orbit_to_geostationary_transfer() -> None:
    result = hohmann_transfer(6678.0, 42164.0)

    assert result["delta_v1_km_s"] == pytest.approx(2.4258, abs=0.001)
    assert result["delta_v2_km_s"] == pytest.approx(1.4668, abs=0.001)
    assert result["total_delta_v_km_s"] == pytest.approx(3.8926, abs=0.002)
    assert result["transfer_seconds"] / 3600.0 == pytest.approx(5.275, abs=0.01)


def test_invalid_radius_is_rejected() -> None:
    with pytest.raises(ValueError):
        hohmann_transfer(0.0, 42164.0)
'''


_README = """# Deterministic Hohmann Transfer

The module uses kilometres and seconds and performs no network access.
"""


def _chat_runtime(root: Path, facade):
    from nous_runtime.chat import ChatRuntime
    from nous_runtime.connectivity.project import ProjectExecutionService
    from nous_runtime.model_runtime.bridges import GatewayChatHandler
    from nous_runtime.runtime.orchestrator import RuntimeOrchestrator

    orchestrator = RuntimeOrchestrator(
        workspace_root=str(root),
        product_handlers={
            "chat": GatewayChatHandler(
                facade,
                checkpoint_root=str(root),
            )
        },
        gate=_ExecuteGate(),
        bootstrap=False,
    )
    return ChatRuntime(
        str(root),
        orchestrator=orchestrator,
        project_execution=ProjectExecutionService(),
    )


@requires_strong_sandbox
def test_aerospace_project_recovers_writes_verifies_and_replays(
    tmp_path: Path, monkeypatch
) -> None:
    from nous_runtime.chat import ChatRequest

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    first_runtime = _chat_runtime(tmp_path, _PauseFacade())
    paused = first_runtime.send(
        ChatRequest(
            "Create code files for an orbital transfer project.",
            "workspace-p7",
            "operator",
            request_id="p7-before-restart",
        )
    )

    paused_link = paused.data["project_execution"]
    paused_agent = paused.data["result"]["execution"]["result"][
        "agent_execution"
    ]
    durable_agent_checkpoint = SQLiteCheckpointStore(
        tmp_path / ".nous" / "agent-checkpoints.db"
    ).load(paused_agent["checkpoint_id"])
    assert paused.status == "failed"
    assert paused_link["status"] == "recovery_required"
    assert paused_link["checkpoint_id"]
    assert paused_link["agent_run_id"] == paused_agent["run_id"]
    assert paused_link["agent_checkpoint_id"] == paused_agent["checkpoint_id"]
    paused_assistant = first_runtime.conversations.history(
        paused.conversation_id
    )[-1]
    assert paused_assistant.metadata["agent_run_id"] == paused_agent["run_id"]
    assert paused_assistant.metadata["agent_checkpoint_id"] == (
        paused_agent["checkpoint_id"]
    )
    assert durable_agent_checkpoint is not None
    assert durable_agent_checkpoint.metadata["run_id"] == paused_agent["run_id"]
    assert not (tmp_path / "aerospace").exists()

    facade = _AerospaceFacade()
    restarted_runtime = _chat_runtime(tmp_path, facade)
    completed = restarted_runtime.send(
        ChatRequest(
            "Create the remaining orbital transfer code files and run checks.",
            "workspace-p7",
            "operator",
            conversation_id=paused.conversation_id,
            request_id="p7-after-restart",
        )
    )

    project_link = completed.data["project_execution"]
    execution = completed.data["result"]["execution"]["result"]
    steps = execution["agent_steps"]
    events = EventStream(str(tmp_path)).load_events("p7-after-restart")
    artifact_events = [
        event for event in events if event.event_type == "artifact.created"
    ]
    tool_events = [
        event for event in events if event.event_type == "tool.completed"
    ]

    assert completed.status == "ok", completed.data
    assert facade.calls == 3
    assert project_link["resumed"] is True
    assert project_link["status"] == "succeeded"
    assert project_link["project_id"] == paused_link["project_id"]
    assert project_link["work_item_id"] == paused_link["work_item_id"]
    assert project_link["checkpoint_id"] != paused_link["checkpoint_id"]
    assert [step["tool"] for step in steps] == ["write_files", "run_command"]
    assert steps[0]["result"]["ok"] is True, steps[0]["result"]
    assert steps[0]["result"]["file_count"] == 3
    assert all(item["receipt_id"] for item in steps[0]["result"]["files"])
    assert steps[1]["result"]["ok"] is True, steps[1]["result"]
    assert steps[1]["result"]["exit_code"] == 0
    assert "2 passed" in steps[1]["result"]["stdout"]
    assert len(artifact_events) == 3
    assert {event.payload["path"] for event in artifact_events} == {
        "aerospace/hohmann.py",
        "aerospace/test_hohmann.py",
        "aerospace/README.md",
    }
    assert set(project_link["artifact_ids"]) == {
        event.payload["artifact_id"] for event in artifact_events
    }
    assert [event.payload["tool"] for event in tool_events] == [
        "write_files",
        "run_command",
    ]
    assert all(event.run_id == "p7-after-restart" for event in events)
    assert all(event.task_id == "p7-after-restart" for event in events)
    assert {
        "model.invocation.started",
        "model.invocation.completed",
        "tool.started",
        "tool.completed",
        "artifact.created",
        "verification.completed",
        "run.completed",
    } <= {event.event_type for event in events}
    assert (tmp_path / "aerospace" / "hohmann.py").read_text(
        encoding="utf-8"
    ) == _HOHMANN_SOURCE
    assert (tmp_path / "aerospace" / "README.md").read_text(
        encoding="utf-8"
    ) == _README
