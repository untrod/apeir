from __future__ import annotations

from collections.abc import Mapping

from nous_runtime.events import RunState
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness
from nous_runtime.work.loop import AgentLoop


class ClosureTools:
    def __init__(self, *, web_error_code: str = "") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.web_error_code = web_error_code
        self.revision = 1

    def specifications(self):
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {"type": "object"},
                },
            }
            for name in ("read_file", "patch_file", "web_fetch")
        )

    def require(self, name):
        effect = "write" if name == "patch_file" else "read"
        return type(
            "Definition",
            (),
            {"effect_class": effect, "capability_id": name},
        )()

    def execute(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "read_file":
            start = max(1, int(arguments.get("start_line") or 1))
            end = max(start, int(arguments.get("end_line") or start + 399))
            return {
                "ok": True,
                "path": arguments["path"],
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
                    "path": arguments["path"],
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
        raise AssertionError(name)


def _decision(tool_name: str, arguments: Mapping[str, object]) -> WorkDecision:
    return WorkDecision(
        DecisionStatus.CONTINUE,
        f"Use {tool_name}",
        next_action=f"Execute {tool_name}",
        tool_name=tool_name,
        tool_arguments=dict(arguments),
    )


def test_covered_range_is_reused_then_patch_invalidates_coverage(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools()
    decisions = iter(
        (
            _decision(
                "read_file",
                {"path": "src/example.py", "start_line": 1, "end_line": 100},
            ),
            _decision(
                "read_file",
                {"path": "./src/example.py", "start_line": 20, "end_line": 30},
            ),
            _decision(
                "patch_file",
                {
                    "path": "src/example.py",
                    "expected": "old",
                    "replacement": "new",
                },
            ),
            _decision(
                "read_file",
                {"path": "src/example.py", "start_line": 20, "end_line": 30},
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "The scripted closure is complete",
                output="done",
            ),
        )
    )

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        max_iterations=8,
    )

    assert completed.state is RunState.COMPLETED
    assert [name for name, _arguments in tools.calls] == [
        "read_file",
        "patch_file",
        "read_file",
    ]
    reuse = next(
        item for item in completed.observations if item["kind"] == "evidence_reuse"
    )
    assert reuse["result"]["already_covered"] is True
    assert reuse["result"]["requested_range"] == [20, 30]
    assert reuse["result"]["covered_range"] == [1, 100]
    reads = [
        item
        for item in completed.observations
        if item["kind"] == "tool" and item["tool"] == "read_file"
    ]
    assert len(reads) == 2
    assert reads[-1]["result"]["sha256"] == "sha256:revision-2"


def test_read_evidence_does_not_complete_coding_step(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Fix the code in this repository")
    tools = ClosureTools()
    read = _decision(
        "read_file",
        {"path": "src/example.py", "start_line": 1, "end_line": 20},
    )
    read = WorkDecision(**{**read.__dict__, "step_id": "execute_1", "phase": "INSPECT"})

    stopped = harness.run(
        created.run_id,
        deliberator=lambda _context: read,
        tools=tools,
        max_iterations=1,
    )

    assert stopped.plan.require_task("execute_1").status.value == "running"


def test_repeated_covered_range_stops_as_action_transition_stall(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools()
    first = _decision(
        "read_file",
        {"path": "src/example.py", "start_line": 1, "end_line": 100},
    )
    repeated = _decision(
        "read_file",
        {"path": "src/example.py", "start_line": 20, "end_line": 30},
    )
    count = 0

    def deliberate(_context):
        nonlocal count
        count += 1
        return first if count == 1 else repeated

    blocked = harness.run(
        created.run_id,
        deliberator=deliberate,
        tools=tools,
        max_iterations=8,
    )

    assert blocked.state is RunState.BLOCKED
    assert blocked.goal.blocker.startswith("ACTION_TRANSITION_STALL:")
    assert len(tools.calls) == 1
    assert count == 3
    assert any(
        event.payload.get("reason_code") == "ACTION_TRANSITION_STALL"
        for event in harness.events.load_events(created.run_id)
    )


def test_retryable_url_failure_is_bounded_to_three_attempts(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools(web_error_code="NETWORK_TIMEOUT")
    decision = _decision("web_fetch", {"url": "https://example.com/issue"})

    blocked = harness.run(
        created.run_id,
        deliberator=lambda _context: decision,
        tools=tools,
        max_iterations=8,
    )

    assert blocked.state is RunState.BLOCKED
    assert blocked.goal.blocker.startswith("URL_RETRY_BUDGET_EXHAUSTED:")
    assert len(tools.calls) == 3
    failures = [
        item["result"]
        for item in blocked.observations
        if item.get("tool") == "web_fetch"
    ]
    assert {item["failure_class"] for item in failures} == {"retryable"}
    assert all(item["retryable"] is True for item in failures)


def test_non_retryable_url_failure_is_not_reissued(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools(web_error_code="NETWORK_SSRF_BLOCKED")
    decision = _decision("web_fetch", {"url": "https://example.com/issue"})

    blocked = harness.run(
        created.run_id,
        deliberator=lambda _context: decision,
        tools=tools,
        max_iterations=4,
    )

    assert blocked.state is RunState.BLOCKED
    assert blocked.goal.blocker.startswith("NON_RETRYABLE_URL_FAILURE:")
    assert len(tools.calls) == 1
    result = blocked.observations[-1]["result"]
    assert result["failure_class"] == "non_retryable"
    assert result["retryable"] is False


def test_unknown_web_failure_is_fail_closed_and_not_marked_retryable():
    failure_class, retryable, code = AgentLoop._classify_web_failure(
        {"ok": False, "error": "unexpected provider response"}
    )

    assert failure_class == "unknown"
    assert retryable is False
    assert code == "WEB_REQUEST_FAILED"


def test_unknown_web_failure_is_not_reissued(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools(web_error_code="UNEXPECTED_PROVIDER_FAILURE")
    decision = _decision("web_fetch", {"url": "https://example.com/issue"})

    blocked = harness.run(
        created.run_id,
        deliberator=lambda _context: decision,
        tools=tools,
        max_iterations=4,
    )

    assert blocked.state is RunState.BLOCKED
    assert blocked.goal.blocker.startswith("UNCLASSIFIED_URL_FAILURE:")
    assert len(tools.calls) == 1


def test_unknown_web_failure_can_transition_to_explicit_approval(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one workspace value")
    tools = ClosureTools(web_error_code="UNEXPECTED_PROVIDER_FAILURE")
    decisions = iter(
        (
            _decision("web_fetch", {"url": "https://example.com/issue"}),
            WorkDecision(
                DecisionStatus.REQUEST_APPROVAL,
                "The governed URL fetch requires explicit approval",
                next_action="Approve the public URL fetch",
                reason="The required public evidence is not available locally",
                tool_name="web_fetch",
                tool_arguments={"url": "https://example.com/issue"},
            ),
        )
    )

    waiting = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        max_iterations=4,
    )

    assert waiting.state is RunState.WAITING_FOR_APPROVAL
    assert (
        waiting.goal.blocker == "The required public evidence is not available locally"
    )
    assert len(tools.calls) == 1
    assert not any(
        event.payload.get("reason_code") == "UNCLASSIFIED_URL_FAILURE"
        for event in harness.events.load_events(created.run_id)
    )


def test_http_status_retry_classification_is_deterministic():
    assert AgentLoop._classify_web_failure(
        {
            "error_code": "NETWORK_HTTP_STATUS",
            "error": "The remote server returned HTTP 429.",
        }
    ) == ("retryable", True, "NETWORK_HTTP_STATUS")
    assert AgentLoop._classify_web_failure(
        {
            "error_code": "NETWORK_HTTP_STATUS",
            "error": "The remote server returned HTTP 404.",
        }
    ) == ("non_retryable", False, "NETWORK_HTTP_STATUS")


def test_connection_reset_is_retryable_even_with_generic_runtime_code():
    assert AgentLoop._classify_web_failure(
        {
            "error_code": "NOUS_RUNTIME_EXECUTION_FAILED",
            "error": "The remote peer reset the connection.",
        }
    ) == ("retryable", True, "NOUS_RUNTIME_EXECUTION_FAILED")
