"""Offline R6 acceptance for revision-aware evidence reuse.

This fixture uses a deterministic deliberator and tool adapter. It never calls a
model provider or the public network.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nous_runtime.events import RunState
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness


class ScriptedTools:
    def __init__(self, *, web_error_code: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.revision = 1
        self.web_error_code = web_error_code

    def specifications(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"offline fixture {name}",
                    "parameters": {"type": "object"},
                },
            }
            for name in ("read_file", "patch_file", "web_fetch")
        )

    def require(self, name: str) -> Any:
        effect = "write" if name == "patch_file" else "read"
        return type(
            "Definition",
            (),
            {"effect_class": effect, "capability_id": name},
        )()

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"tool": name, "arguments": dict(arguments)})
        if name == "read_file":
            start = max(1, int(arguments.get("start_line") or 1))
            end = max(start, int(arguments.get("end_line") or start + 399))
            return {
                "ok": True,
                "path": str(arguments["path"]),
                "start_line": start,
                "end_line": end,
                "content": f"revision {self.revision}",
                "sha256": f"sha256:revision-{self.revision}",
            }
        if name == "patch_file":
            self.revision += 1
            return {
                "ok": True,
                "change": {
                    "path": str(arguments["path"]),
                    "operation": "patch",
                    "before_digest": "sha256:revision-1",
                    "after_digest": "sha256:revision-2",
                    "lines_added": 1,
                    "lines_removed": 1,
                },
            }
        if name == "web_fetch":
            return {
                "ok": False,
                "error": self.web_error_code,
                "error_code": self.web_error_code,
            }
        raise ValueError(f"unsupported fixture tool: {name}")


def decision(tool: str, arguments: Mapping[str, Any]) -> WorkDecision:
    return WorkDecision(
        DecisionStatus.CONTINUE,
        f"Use {tool}",
        next_action=f"Execute {tool}",
        tool_name=tool,
        tool_arguments=dict(arguments),
    )


def run_reuse_and_invalidation(root: Path) -> dict[str, Any]:
    harness = WorkHarness(root / "reuse")
    created = harness.create("Explain one workspace value")
    tools = ScriptedTools()
    decisions = iter(
        (
            decision(
                "read_file",
                {"path": "src/example.py", "start_line": 1, "end_line": 100},
            ),
            decision(
                "read_file",
                {"path": "src/example.py", "start_line": 20, "end_line": 30},
            ),
            decision(
                "patch_file",
                {
                    "path": "src/example.py",
                    "expected": "old",
                    "replacement": "new",
                },
            ),
            decision(
                "read_file",
                {"path": "src/example.py", "start_line": 20, "end_line": 30},
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "Offline evidence-reuse work completed",
                output="done",
            ),
        )
    )
    result = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        max_iterations=8,
    )
    reuse = [
        item for item in result.observations if item.get("kind") == "evidence_reuse"
    ]
    reads = [call for call in tools.calls if call["tool"] == "read_file"]
    passed = (
        result.state is RunState.COMPLETED
        and len(reuse) == 1
        and len(reads) == 2
        and reuse[0]["result"]["already_covered"] is True
        and reads[-1]["arguments"]["start_line"] == 20
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "work_id": result.run_id,
        "state": result.state.value,
        "tool_sequence": [call["tool"] for call in tools.calls],
        "reuse": reuse[0]["result"] if reuse else {},
        "post_mutation_read_count": max(0, len(reads) - 1),
    }


def run_transition_stall(root: Path) -> dict[str, Any]:
    harness = WorkHarness(root / "stall")
    created = harness.create("Explain one workspace value")
    tools = ScriptedTools()
    first = decision(
        "read_file",
        {"path": "src/example.py", "start_line": 1, "end_line": 100},
    )
    repeated = decision(
        "read_file",
        {"path": "src/example.py", "start_line": 20, "end_line": 30},
    )
    iterations = 0

    def deliberate(_context: Any) -> WorkDecision:
        nonlocal iterations
        iterations += 1
        return first if iterations == 1 else repeated

    result = harness.run(
        created.run_id,
        deliberator=deliberate,
        tools=tools,
        max_iterations=8,
    )
    passed = (
        result.state is RunState.BLOCKED
        and result.goal.blocker.startswith("ACTION_TRANSITION_STALL:")
        and len(tools.calls) == 1
        and iterations == 3
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "work_id": result.run_id,
        "state": result.state.value,
        "blocker": result.goal.blocker,
        "model_decisions": iterations,
        "tool_calls": len(tools.calls),
    }


def run_url_budget(root: Path, error_code: str) -> dict[str, Any]:
    harness = WorkHarness(root / error_code.casefold())
    created = harness.create("Explain one workspace value")
    tools = ScriptedTools(web_error_code=error_code)
    action = decision("web_fetch", {"url": "https://example.com/issue"})
    result = harness.run(
        created.run_id,
        deliberator=lambda _context: action,
        tools=tools,
        max_iterations=8,
    )
    expected_code = (
        "NON_RETRYABLE_URL_FAILURE"
        if error_code == "NETWORK_SSRF_BLOCKED"
        else "URL_RETRY_BUDGET_EXHAUSTED"
    )
    expected_calls = 1 if error_code == "NETWORK_SSRF_BLOCKED" else 3
    passed = (
        result.state is RunState.BLOCKED
        and result.goal.blocker.startswith(expected_code + ":")
        and len(tools.calls) == expected_calls
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "work_id": result.run_id,
        "state": result.state.value,
        "blocker": result.goal.blocker,
        "tool_calls": len(tools.calls),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="apeir-r6-evidence-") as temporary:
        root = Path(temporary)
        checks = {
            "revision_aware_reuse": run_reuse_and_invalidation(root),
            "action_transition_stall": run_transition_stall(root),
            "retryable_url_budget": run_url_budget(root, "NETWORK_TIMEOUT"),
            "non_retryable_url_failure": run_url_budget(root, "NETWORK_SSRF_BLOCKED"),
        }
    passed = all(item["status"] == "PASS" for item in checks.values())
    report = {
        "schema": "apeir.r6-evidence-reuse-acceptance/v1",
        "offline": True,
        "paid_model_calls": 0,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
