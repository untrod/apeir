# -*- coding: utf-8 -*-
"""Read software-test outcomes from the original workspace EventStream."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind
from nous_runtime.core.redaction import redact_sensitive_data


class TestValidator:
    """Inspect recorded tests; evaluation never executes project code."""

    dimension: str = EvaluationDimension.CORRECTNESS.value
    source: str = "pytest"
    __test__ = False  # Production helper, not a pytest test class.

    @staticmethod
    def unittest_outcome(
        stderr: str, exit_code: int, *, complete: bool
    ) -> dict[str, Any]:
        """Inspect an existing isolated unittest receipt; never execute a child.

        Counters describe reported software tests, not independent physical
        verification. Missing/all-skipped/truncated evidence cannot pass.
        """
        summaries = list(re.finditer(r"(?m)^Ran (\d+) tests? in [0-9.]+s\s*$", stderr))
        counts = None
        outcome = "FAIL" if exit_code else "UNKNOWN"
        if summaries:
            summary = summaries[-1]
            total = int(summary.group(1))
            tail = stderr[summary.end() :].strip()
            status = re.fullmatch(r"(OK|FAILED)(?: \(([^\n]*)\))?", tail)
            if status:
                raw_fields = status.group(2) or ""
                field_pattern = r"(?:skipped|failures|errors|expected failures|unexpected successes)=\d+"
                if (
                    raw_fields
                    and re.fullmatch(
                        field_pattern + r"(?:, " + field_pattern + r")*", raw_fields
                    )
                    is None
                ):
                    return {
                        "test_framework": "unittest",
                        "test_outcome": outcome,
                        "test_counts": None,
                    }
                fields = dict(
                    (key, int(value))
                    for key, value in re.findall(
                        r"(skipped|failures|errors|expected failures|unexpected successes)=(\d+)",
                        status.group(2) or "",
                    )
                )
                if (
                    len(fields) != len(re.findall(r"=\d+", raw_fields))
                    or sum(fields.values()) > total
                ):
                    return {
                        "test_framework": "unittest",
                        "test_outcome": outcome,
                        "test_counts": None,
                    }
                counts = {
                    "run": total,
                    "passed": max(0, total - sum(fields.values())),
                    **fields,
                }
                if (
                    complete
                    and exit_code == 0
                    and status.group(1) == "OK"
                    and counts["passed"] > 0
                    and not any(
                        fields.get(k, 0)
                        for k in ("failures", "errors", "unexpected successes")
                    )
                ):
                    outcome = "PASS"
        return {
            "test_framework": "unittest",
            "test_outcome": outcome,
            "test_counts": counts,
        }

    def __init__(self, workspace: str = "") -> None:
        self._workspace = workspace

    @staticmethod
    def pytest_outcome(
        stdout: str, exit_code: int, *, complete: bool
    ) -> dict[str, Any]:
        counts = None
        for line in stdout.splitlines():
            fields = re.findall(
                r"(\d+)\s+(passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)\b",
                line,
            )
            if fields:
                counts = {
                    key.rstrip("s") if key in {"errors", "warnings"} else key: int(
                        value
                    )
                    for value, key in fields
                }
        total = sum(
            (counts or {}).get(key, 0)
            for key in ("passed", "failed", "skipped", "error", "xfailed", "xpassed")
        )
        passed = (
            complete
            and exit_code == 0
            and (counts or {}).get("passed", 0) > 0
            and not any((counts or {}).get(key, 0) for key in ("failed", "error"))
        )
        return {
            "test_framework": "pytest",
            "test_outcome": "PASS" if passed else "FAIL" if exit_code else "UNKNOWN",
            "test_counts": counts,
            "test_count": total if counts is not None else None,
        }

    def validate(
        self, target: Any, context: dict[str, Any] | None = None
    ) -> list[EvaluationEvidence]:
        from nous_runtime.events import EventStream, RunState

        ctx = context or {}
        root = Path(
            self._workspace or os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()
        ).resolve()
        if root.name == ".nous":
            root = root.parent
        run_id = ctx.get("test_run_id") or ctx.get("run_id")
        detail: dict[str, Any] = {
            "run_id": run_id if isinstance(run_id, str) else None,
            "returncode": None,
            "test_counts": None,
            "test_count": None,
        }
        framework = self.source
        outcome = "UNKNOWN"
        counts = None
        try:
            if not isinstance(run_id, str) or not run_id:
                raise ValueError(
                    "an original test_run_id is required; evaluation does not run tests"
                )
            events = EventStream(str(root))
            original = events.get_run(run_id)
            if original is None:
                raise ValueError("test Run is not present in this workspace")
            recorded = events.load_events(run_id)
            completed = [
                e
                for e in recorded
                if e.actor == "developer.workbench" and e.event_type == "test.completed"
            ]
            if len(completed) != 1:
                raise ValueError("test Run has no unique canonical completion receipt")
            payload = completed[0].payload
            profile = payload.get("profile")
            if profile not in {"pytest", "python-unittest"}:
                raise ValueError("the recorded profile is not a supported test runner")
            exit_code = payload.get("exit_code")
            if type(exit_code) is not int:
                raise ValueError("test Run has no actual exit code")
            streams = {"stdout": "", "stderr": ""}
            for event in recorded:
                if (
                    event.actor == "developer.workbench"
                    and event.event_type == "command.output"
                ):
                    stream = event.payload.get("stream")
                    if stream in streams:
                        streams[stream] += str(event.payload.get("text") or "")
                        if len(streams[stream]) > 10_485_760:
                            raise ValueError("test output exceeds the evidence bound")
            complete = (
                original.state is RunState.COMPLETED
                and payload.get("ok") is True
                and not payload.get("limit_exceeded")
            )
            parsed = (
                self.unittest_outcome(streams["stderr"], exit_code, complete=complete)
                if profile == "python-unittest"
                else self.pytest_outcome(
                    streams["stdout"], exit_code, complete=complete
                )
            )
            framework = parsed["test_framework"]
            outcome = parsed["test_outcome"]
            counts = parsed["test_counts"]
            total = (
                counts["run"]
                if framework == "unittest" and counts is not None
                else parsed.get("test_count")
            )
            detail.update(
                {
                    "returncode": exit_code,
                    "test_counts": counts,
                    "test_count": total,
                    "input_snapshot_sha256": payload.get("input_snapshot_sha256"),
                    "stdout_tail": streams["stdout"][-500:],
                    "stderr_tail": streams["stderr"][-200:],
                }
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            detail["error"] = str(exc)
        passed = outcome == "PASS"
        detail["test_outcome"] = outcome
        score = (
            1.0
            if passed
            else 0.5
            if detail["returncode"] and (counts or {}).get("passed", 0)
            else 0.0
        )
        count = detail["test_count"]
        return [
            EvaluationEvidence(
                kind=EvidenceKind.TEST_RESULT.value,
                dimension=self.dimension,
                summary=f"{framework}: {outcome} ({count if count is not None else 'UNKNOWN'} tests)",
                passed=passed,
                score=score,
                source=framework,
                detail=redact_sensitive_data(detail),
            )
        ]
