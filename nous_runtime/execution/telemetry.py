# -*- coding: utf-8 -*-
"""Execution telemetry — versioned, sanitized, audit-ready task tracing.

Collects structured telemetry for every task execution and produces
machine-readable output to the configured local audit directory.

Schema version: 1.0.0

Design rules:
    - Default-sanitized: never log user prompt content or raw tool output.
    - Append-only JSONL for task traces.
    - Aggregated metrics to JSON for dashboards.
    - Thread-safe recording.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.schema_registry import TELEMETRY_SCHEMA_VERSION


# Data models


@dataclass
class TaskTrace:
    """Single task execution trace record (one JSONL line)."""

    schema_version: str = TELEMETRY_SCHEMA_VERSION
    trace_id: str = ""
    task_type: str = ""                # e.g. "code_audit", "bug_fix", "test_gen"
    candidate_plans: int = 0           # number of candidate plans generated
    selected_plan: str = ""            # identifier of selected plan
    rejection_reasons: list[str] = field(default_factory=list)
    model_id: str = ""
    provider_id: str = ""
    model_version: str = ""
    node_id: str = ""                  # execution node
    node_platform: str = ""            # e.g. "windows-x86_64", "linux-arm64"
    prompt_template_version: str = ""
    tool_sequence: list[str] = field(default_factory=list)  # ordered tool IDs used
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    queue_time_ms: int = 0             # time spent in queue before execution
    execution_time_ms: int = 0         # wall-clock execution duration
    retries: int = 0
    errors: list[str] = field(default_factory=list)  # error codes encountered
    verification_result: str = ""       # "pass", "fail", "warning", "skipped"
    artifact_count: int = 0
    artifact_ids: list[str] = field(default_factory=list)
    recovery_triggered: bool = False
    recovery_success: bool = False
    human_intervention: bool = False
    human_approval_required: bool = False
    human_approval_granted: bool = False
    user_feedback: str = ""            # sanitized category only: "thumbs_up", "thumbs_down", ""
    started_at: str = ""
    completed_at: str = ""
    status: str = ""                   # "success", "failure", "cancelled", "timeout"

    def to_jsonl(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


@dataclass
class AggregatedMetrics:
    """Aggregated metrics over a batch of task traces (one JSON file)."""

    schema_version: str = TELEMETRY_SCHEMA_VERSION
    run_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    total_tasks: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    tasks_cancelled: int = 0

    # Rates
    task_success_rate: float = 0.0
    verified_success_rate: float = 0.0
    false_completion_rate: float = 0.0
    recovery_success_rate: float = 0.0
    human_intervention_rate: float = 0.0
    artifact_integrity_rate: float = 0.0
    event_loss_rate: float = 0.0
    duplicate_execution_rate: float = 0.0
    provider_failure_rate: float = 0.0
    repeatability_rate: float = 0.0

    # Latency (ms)
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0

    # Cost
    total_cost_usd: float = 0.0
    cost_per_verified_task_usd: float = 0.0

    # Resources
    total_tokens: int = 0
    node_utilization_pct: float = 0.0
    routing_regret_count: int = 0

    # Errors
    top_error_codes: list[tuple[str, int]] = field(default_factory=list)  # (code, count)

    # Models
    models_used: list[str] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)



# Recorder (thread-safe)


class TelemetryRecorder:
    """Thread-safe telemetry collector for a single run.

    Usage:
        recorder = TelemetryRecorder(audit_dir)
        recorder.start()
        # ... run tasks ...
        recorder.record(trace)
        recorder.finish()
    """

    def __init__(self, audit_dir: str | Path) -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._started_at: str = ""
        self._completed_at: str = ""
        self._lock = threading.Lock()
        self._traces: list[TaskTrace] = []
        self._event_loss_count: int = 0
        self._duplicate_count: int = 0
        self._trace_path: Path | None = None

    def start(self) -> None:
        """Begin a new telemetry run."""
        self._started_at = _utc_now()
        self._trace_path = self.audit_dir / f"rc1-task-traces-{self.run_id}.jsonl"
        # Write header comment
        header = {
            "type": "telemetry_run_start",
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": self._started_at,
        }
        self._append_jsonl(header)

    def record(self, trace: TaskTrace) -> None:
        """Record a single task trace (thread-safe)."""
        trace.trace_id = trace.trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        if not trace.started_at:
            trace.started_at = _utc_now()
        with self._lock:
            self._traces.append(trace)
            self._append_jsonl(asdict(trace))

    def record_event_loss(self, count: int = 1) -> None:
        with self._lock:
            self._event_loss_count += count

    def record_duplicate(self) -> None:
        with self._lock:
            self._duplicate_count += 1

    def finish(self) -> AggregatedMetrics:
        """Compute aggregated metrics and write to .audit/."""
        self._completed_at = _utc_now()
        metrics = self._compute_metrics()
        metrics_path = self.audit_dir / f"rc1-metrics-{self.run_id}.json"
        metrics_path.write_text(
            json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # Write run end marker
        footer = {
            "type": "telemetry_run_end",
            "run_id": self.run_id,
            "completed_at": self._completed_at,
            "total_traces": metrics.total_tasks,
        }
        self._append_jsonl(footer)
        return metrics

    def _compute_metrics(self) -> AggregatedMetrics:
        traces = list(self._traces)
        m = AggregatedMetrics(
            run_id=self.run_id,
            started_at=self._started_at,
            completed_at=self._completed_at,
        )
        if not traces:
            return m

        m.total_tasks = len(traces)
        m.tasks_succeeded = sum(1 for t in traces if t.status == "success")
        m.tasks_failed = sum(1 for t in traces if t.status == "failure")
        m.tasks_cancelled = sum(1 for t in traces if t.status == "cancelled")

        # Success rate
        finished = m.tasks_succeeded + m.tasks_failed
        m.task_success_rate = m.tasks_succeeded / max(finished, 1)

        # Verified success rate
        verified = sum(1 for t in traces if t.verification_result == "pass")
        m.verified_success_rate = verified / max(finished, 1)

        # False completion rate
        false_completions = sum(
            1 for t in traces
            if t.status == "success" and t.verification_result == "fail"
        )
        m.false_completion_rate = false_completions / max(finished, 1)

        # Recovery
        recoveries = sum(1 for t in traces if t.recovery_triggered)
        if recoveries > 0:
            m.recovery_success_rate = sum(
                1 for t in traces if t.recovery_triggered and t.recovery_success
            ) / recoveries

        # Human intervention
        m.human_intervention_rate = sum(
            1 for t in traces if t.human_intervention
        ) / m.total_tasks

        # Artifact integrity
        artifacts_total = sum(t.artifact_count for t in traces)
        artifacts_ok = artifacts_total  # default: assume OK unless reported otherwise
        m.artifact_integrity_rate = artifacts_ok / max(artifacts_total, 1)

        # Event loss
        m.event_loss_rate = self._event_loss_count / max(m.total_tasks, 1)

        # Duplicate execution
        m.duplicate_execution_rate = self._duplicate_count / max(m.total_tasks, 1)

        # Provider failure
        provider_errors = sum(
            1 for t in traces
            if any("provider" in e.lower() or "rate_limit" in e.lower() for e in t.errors)
        )
        m.provider_failure_rate = provider_errors / max(finished, 1)

        # Latency percentiles
        latencies = sorted(
            t.execution_time_ms for t in traces if t.execution_time_ms > 0
        )
        if latencies:
            m.latency_p50_ms = _percentile(latencies, 50)
            m.latency_p95_ms = _percentile(latencies, 95)
            m.latency_p99_ms = _percentile(latencies, 99)

        # Cost
        m.total_cost_usd = sum(t.cost_usd for t in traces)
        m.cost_per_verified_task_usd = m.total_cost_usd / max(verified, 1)

        # Tokens
        m.total_tokens = sum(t.tokens_input + t.tokens_output for t in traces)

        # Models and providers
        m.models_used = sorted(set(t.model_id for t in traces if t.model_id))
        m.providers_used = sorted(set(t.provider_id for t in traces if t.provider_id))

        # Top errors
        error_counts: dict[str, int] = {}
        for t in traces:
            for e in t.errors:
                error_counts[e] = error_counts.get(e, 0) + 1
        m.top_error_codes = sorted(error_counts.items(), key=lambda x: -x[1])[:10]

        # Routing regret
        m.routing_regret_count = sum(
            1 for t in traces if t.retries > 0 and t.status == "failure"
        )

        return m

    def _append_jsonl(self, record: dict | Any) -> None:
        if self._trace_path is None:
            return
        line = json.dumps(
            record if isinstance(record, dict) else asdict(record),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with open(self._trace_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")



# Helpers


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute percentile from sorted list."""
    if not sorted_values:
        return 0.0
    k = (pct / 100.0) * (len(sorted_values) - 1)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])
