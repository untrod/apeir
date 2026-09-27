"""Offline R6 acceptance for the complete governed code-work transition.

The fixture performs a real file patch, Persistent Shell pytest run, Git diff
review, deterministic verification, and Work completion.  Its deliberator is
scripted, so it never calls a model provider or the public network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.events import RunState
from nous_runtime.tools import GitToolRuntime, ProcessSessionToolRuntime, ToolCatalog
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness
from nous_runtime.work.deliberation import verify_recorded_work


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _prepare_fixture(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    # The implementation should add both operands.\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_calculator.py").write_text(
        "from src.calculator import add\n\n\n"
        "def test_adds_both_operands():\n"
        "    assert add(7, 5) == 12\n",
        encoding="utf-8",
    )
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.name", "APEIR Acceptance")
    _run_git(root, "config", "user.email", "acceptance@example.invalid")
    _run_git(root, "add", "src/calculator.py", "tests/test_calculator.py")
    _run_git(root, "commit", "-q", "-m", "fixture baseline")


def _tools(root: Path) -> ToolCatalog:
    workspace = WorkspaceToolRuntime(str(root), allow_mutations=True)
    catalog = ToolCatalog()
    catalog.register_runtime(workspace, excluded_tool_ids={"run_command"})
    catalog.register_runtime(
        ProcessSessionToolRuntime(workspace),
        provider_id="process-session",
    )
    catalog.register_runtime(GitToolRuntime(root), provider_id="git-sandbox")
    return catalog


def _tool_observations(context: Any) -> list[Mapping[str, Any]]:
    return [
        item
        for item in context.recent_observations
        if item.get("kind") == "tool" and isinstance(item.get("result"), Mapping)
    ]


def _coding_step(context: Any) -> str:
    for task in (context.plan or {}).get("tasks") or ():
        if task.get("capability_id") == "coding":
            return str(task.get("task_id") or "")
    return ""


class CodeWorkScript:
    """Select the next action from durable facts, never hidden local state."""

    def __call__(self, context: Any) -> WorkDecision:
        observations = _tool_observations(context)
        successful = [item for item in observations if item.get("ok") is True]
        step_id = _coding_step(context)
        if not any(item.get("tool") == "read_file" for item in successful):
            return WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect the implementation before changing it",
                next_action="Read the calculator source",
                tool_name="read_file",
                tool_arguments={"path": "src/calculator.py", "start_line": 1},
                step_id=step_id,
                phase="INSPECT",
            )
        if not any(item.get("tool") == "patch_file" for item in successful):
            return WorkDecision(
                DecisionStatus.CONTINUE,
                "The subtraction operator contradicts the required addition behavior",
                next_action="Apply the smallest exact source patch",
                tool_name="patch_file",
                tool_arguments={
                    "path": "src/calculator.py",
                    "expected": "    return left - right\n",
                    "replacement": "    return left + right\n",
                },
                step_id=step_id,
                phase="ACT",
                action_source="provider_native_tool_call",
            )
        shell = [
            item
            for item in successful
            if item.get("tool") in {"shell_start", "shell_status"}
        ]
        if not any(item.get("tool") == "shell_start" for item in shell):
            return WorkDecision(
                DecisionStatus.CONTINUE,
                "The workspace changed and now requires targeted validation",
                next_action="Run the focused calculator test in Persistent Shell",
                tool_name="shell_start",
                tool_arguments={
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "-q",
                        "tests/test_calculator.py",
                    ],
                    "cwd": ".",
                },
                phase="VERIFY",
                action_source="provider_native_tool_call",
            )
        shell_result = dict(shell[-1]["result"])
        if shell_result.get("state") not in {"EXITED", "FAILED", "TERMINATED"}:
            # A real provider round trip naturally gives the process time to advance.
            # The offline fixture is instantaneous, so make one bounded wait before
            # observing the same durable session again.
            time.sleep(1.0)
            return WorkDecision(
                DecisionStatus.CONTINUE,
                "The targeted test process has not reached a terminal state",
                next_action="Observe the existing process without replaying it",
                tool_name="shell_status",
                tool_arguments={"session_id": shell_result["session_id"]},
                phase="WAIT",
            )
        if shell_result.get("state") != "EXITED" or shell_result.get("exit_code") != 0:
            return WorkDecision(
                DecisionStatus.FAIL,
                "The targeted calculator test failed",
                reason="targeted test did not exit successfully",
                phase="VERIFY",
            )
        if not any(item.get("tool") == "git_diff" for item in successful):
            return WorkDecision(
                DecisionStatus.CONTINUE,
                "The targeted test passed; review the actual workspace diff",
                next_action="Inspect the source diff",
                tool_name="git_diff",
                tool_arguments={"path": "src/calculator.py"},
                phase="VERIFY",
            )
        verified = any(
            item.get("kind") == "verification" and item.get("ok") is True
            for item in context.recent_observations
        )
        if not verified:
            return WorkDecision(
                DecisionStatus.VERIFY,
                "Mutation, targeted test, and diff evidence are recorded",
                next_action="Evaluate the deterministic completion gate",
                phase="VERIFY",
            )
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "The calculator defect is fixed and independently verified",
            output={"status": "fixed", "test": "tests/test_calculator.py"},
            phase="COMPLETE",
        )


def run_acceptance(root: Path) -> dict[str, Any]:
    _prepare_fixture(root)
    harness = WorkHarness(root)
    snapshot = harness.create(
        "Fix the calculator defect with the smallest correct source change, "
        "run the targeted test, review the diff, and verify completion"
    )
    result = harness.run(
        snapshot.run_id,
        deliberator=CodeWorkScript(),
        tools=_tools(root),
        verifier=verify_recorded_work,
        max_iterations=12,
    )
    observations = list(result.observations)
    tool_sequence = [
        str(item.get("tool"))
        for item in observations
        if item.get("kind") == "tool" and item.get("tool") not in {"catalog_expand"}
    ]
    verification = [
        dict(item.get("result") or {})
        for item in observations
        if item.get("kind") == "verification"
    ]
    final_source = (root / "src" / "calculator.py").read_text(encoding="utf-8")
    required_tools = {"read_file", "patch_file", "shell_start", "git_diff"}
    receipts = [
        str((item.get("result") or {}).get("receipt_id") or "")
        for item in observations
        if item.get("kind") == "tool"
        and isinstance(item.get("result"), Mapping)
        and (item.get("result") or {}).get("receipt_id")
    ]
    failed_tools = [
        {
            "tool": str(item.get("tool") or ""),
            "error": str((item.get("result") or {}).get("error") or ""),
            "error_code": str((item.get("result") or {}).get("error_code") or ""),
            "state": str((item.get("result") or {}).get("state") or ""),
            "exit_code": (item.get("result") or {}).get("exit_code"),
            "stderr": str((item.get("result") or {}).get("stderr") or "")[-500:],
        }
        for item in observations
        if item.get("kind") == "tool" and item.get("ok") is not True
    ]
    passed = (
        result.state is RunState.COMPLETED
        and required_tools.issubset(set(tool_sequence))
        and "return left + right" in final_source
        and bool(verification)
        and verification[-1].get("ok") is True
        and verification[-1].get("missing_progress_facts") == []
        and bool(receipts)
    )
    return {
        "schema": "apeir.r6-action-transition-acceptance/v1",
        "offline": True,
        "paid_model_calls": 0,
        "status": "PASS" if passed else "FAIL",
        "work_id": result.run_id,
        "work_state": result.state.value,
        "blocker": result.goal.blocker,
        "error": result.error,
        "tool_sequence": tool_sequence,
        "effect_receipts": receipts,
        "failed_tools": failed_tools,
        "verification": verification[-1] if verification else {},
        "final_source_sha256": _sha256(root / "src" / "calculator.py"),
    }


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="apeir-r6-action-", ignore_cleanup_errors=True
    ) as temporary:
        report = run_acceptance(Path(temporary))
        # The process host writes its terminal state before releasing its log handle.
        # Give that helper a bounded grace period so Windows can remove the fixture.
        time.sleep(0.5)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
