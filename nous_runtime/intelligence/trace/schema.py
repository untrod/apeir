# -*- coding: utf-8 -*-
"""Versioned Execution Trace Record schema.

Captures the complete lifecycle of every task execution across
5 groups: task_info, environment, decision, execution, outcome.

Schema version: 1.0.0 (frozen for Batch 1)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.schema_registry import TELEMETRY_SCHEMA_VERSION

TRACE_SCHEMA_VERSION = TELEMETRY_SCHEMA_VERSION  # "1.0.0"



# Sub-records


@dataclass
class TraceTaskInfo:
    """Task identity and requirements."""
    task_id: str = ""
    task_type: str = ""           # code_audit, bug_fix, test_gen, research, etc.
    domain: str = ""              # software, data, security, etc.
    modalities: list[str] = field(default_factory=list)  # text, code, image, etc.
    input_size_bytes: int = 0
    context_size_bytes: int = 0
    repository_size_bytes: int = 0
    risk_class: str = ""          # low, medium, high, critical
    privacy_class: str = ""       # public, internal, confidential, restricted
    deadline_seconds: int = 0     # 0 = no deadline
    budget_usd: float = 0.0       # 0 = no budget
    user_preferences: dict[str, str] = field(default_factory=dict)


@dataclass
class TraceEnvironment:
    """Execution environment at task start."""
    node_id: str = ""
    operating_system: str = ""
    architecture: str = ""        # x86_64, arm64, etc.
    cpu_cores: int = 0
    memory_mb: int = 0
    gpu_name: str = ""
    gpu_memory_mb: int = 0
    disk_free_mb: int = 0
    network_type: str = ""        # local, remote, vpn, etc.
    runtime_version: str = ""
    model_versions: dict[str, str] = field(default_factory=dict)  # model_id → version
    tool_versions: dict[str, str] = field(default_factory=dict)    # tool_id → version


@dataclass
class TraceDecision:
    """Decision-making trace."""
    candidate_plans: int = 0
    feasible_plans: int = 0
    rejected_plans: list[str] = field(default_factory=list)  # plan IDs
    rejection_reasons: dict[str, str] = field(default_factory=dict)  # plan_id → reason
    hard_constraints: list[str] = field(default_factory=list)  # constraint names
    soft_preferences: list[str] = field(default_factory=list)   # preference names
    selected_plan: str = ""       # plan ID
    decision_policy: str = ""     # policy name
    decision_policy_version: str = ""
    uncertainty: float = 0.0      # 0-1
    confidence: float = 0.0       # 0-1
    human_override: bool = False


@dataclass
class TraceExecution:
    """Execution dynamics."""
    execution_graph: dict[str, Any] = field(default_factory=dict)  # DAG structure
    agent_roles: list[str] = field(default_factory=list)           # role names used
    model_assignments: dict[str, str] = field(default_factory=dict)  # role → model_id
    node_assignments: dict[str, str] = field(default_factory=dict)   # role → node_id
    tool_sequence: list[str] = field(default_factory=list)           # ordered tool IDs
    context_changes: list[str] = field(default_factory=list)         # context mutation log
    checkpoints: int = 0
    retries: int = 0
    replans: int = 0
    failures: list[str] = field(default_factory=list)    # error codes
    recoveries: list[str] = field(default_factory=list)  # recovery actions
    approvals: int = 0                                     # approval count


@dataclass
class TraceOutcome:
    """Task outcome and verification."""
    final_status: str = ""        # success, failure, cancelled, timeout
    verification_status: str = "" # pass, fail, warning, skipped
    quality_metrics: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    queue_time_ms: float = 0.0
    cost_usd: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)  # input, output, total
    resource_usage: dict[str, float] = field(default_factory=dict)  # cpu, memory, disk
    artifact_ids: list[str] = field(default_factory=list)
    human_intervention: bool = False
    user_feedback: str = ""       # thumbs_up, thumbs_down, ""
    repeatability: bool = False   # same input → same output?
    false_completion: bool = False  # marked success but verification failed



# Main record


@dataclass
class ExecutionTraceRecord:
    """Complete versioned execution trace.

    This is the canonical trace record produced after every task.
    It is the primary input to: Dataset Registry, Replay System,
    Metrics Computer, and all downstream intelligence.
    """
    # Identity
    trace_id: str = ""
    schema_version: str = TRACE_SCHEMA_VERSION
    sequence: int = 0             # monotonic sequence number
    created_at: str = ""

    # Sub-records
    task_info: TraceTaskInfo = field(default_factory=TraceTaskInfo)
    environment: TraceEnvironment = field(default_factory=TraceEnvironment)
    decision: TraceDecision = field(default_factory=TraceDecision)
    execution: TraceExecution = field(default_factory=TraceExecution)
    outcome: TraceOutcome = field(default_factory=TraceOutcome)

    # Links
    session_id: str = ""
    parent_trace_id: str = ""     # for retry/replan chains
    event_sequence_range: tuple[int, int] = (0, 0)  # (first, last) event seq

    # Integrity
    content_hash: str = ""        # SHA-256 of sanitized content
    sanitization_level: str = ""  # none, basic, strict, anonymous

    # Methods

    def compute_hash(self) -> str:
        """SHA-256 over deterministic dict representation."""
        d = self.to_dict()
        # Remove hash itself before hashing
        d.pop("content_hash", None)
        canonical = json.dumps(d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def seal(self) -> None:
        """Finalize: set hash and timestamp."""
        self.created_at = self.created_at or _utc_now()
        self.content_hash = self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "parent_trace_id": self.parent_trace_id,
            "event_sequence_range": list(self.event_sequence_range),
            "content_hash": self.content_hash,
            "sanitization_level": self.sanitization_level,
            "task_info": asdict(self.task_info),
            "environment": asdict(self.environment),
            "decision": asdict(self.decision),
            "execution": asdict(self.execution),
            "outcome": asdict(self.outcome),
        }

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionTraceRecord":
        er = data.get("event_sequence_range", [0, 0])
        return cls(
            trace_id=str(data.get("trace_id", "")),
            schema_version=str(data.get("schema_version", TRACE_SCHEMA_VERSION)),
            sequence=int(data.get("sequence", 0)),
            created_at=str(data.get("created_at", "")),
            session_id=str(data.get("session_id", "")),
            parent_trace_id=str(data.get("parent_trace_id", "")),
            event_sequence_range=(int(er[0]), int(er[1])) if isinstance(er, list) and len(er) >= 2 else (0, 0),
            content_hash=str(data.get("content_hash", "")),
            sanitization_level=str(data.get("sanitization_level", "")),
            task_info=TraceTaskInfo(**data.get("task_info", {})),
            environment=TraceEnvironment(**data.get("environment", {})),
            decision=TraceDecision(**data.get("decision", {})),
            execution=TraceExecution(**data.get("execution", {})),
            outcome=TraceOutcome(**data.get("outcome", {})),
        )

    @classmethod
    def new(
        cls,
        *,
        task_id: str = "",
        task_type: str = "",
        session_id: str = "",
        sequence: int = 0,
    ) -> "ExecutionTraceRecord":
        """Create a new trace with defaults."""
        return cls(
            trace_id=f"etr_{uuid.uuid4().hex[:16]}",
            sequence=sequence,
            created_at=_utc_now(),
            session_id=session_id,
            task_info=TraceTaskInfo(
                task_id=task_id or f"task_{uuid.uuid4().hex[:12]}",
                task_type=task_type,
            ),
        )



# Helpers


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
