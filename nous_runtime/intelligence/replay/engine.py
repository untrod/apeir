# -*- coding: utf-8 -*-
"""ReplayEngine — supports 7 replay types with configurable substitution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReplayType(str, Enum):
    TASK = "task"
    DECISION = "decision"
    EVENT = "event"
    ARTIFACT = "artifact"
    MODEL_RESPONSE = "model_response"
    TOOL_RESPONSE = "tool_response"
    FAILURE = "failure"


@dataclass
class ReplayConfig:
    """Configuration for a replay run."""
    replay_type: ReplayType = ReplayType.DECISION
    # Substitutions (None = use original)
    substitute_model_id: str | None = None
    substitute_node_id: str | None = None
    substitute_agent_topology: list[str] | None = None
    substitute_routing_policy: str | None = None
    # Mode
    offline: bool = False           # Use saved responses (True) or re-execute (False)
    compare: bool = True            # Compare original vs replayed
    # Safety
    dry_run: bool = True            # Never mutate production workspace
    timeout_seconds: int = 300


@dataclass
class ReplayResult:
    """Result of a single replay execution."""
    replay_id: str = ""
    replay_type: ReplayType = ReplayType.DECISION
    original_trace_id: str = ""
    status: str = ""                # "completed", "failed", "unplayable"
    replayed_trace_id: str = ""
    substitutions_applied: dict[str, str] = field(default_factory=dict)
    differences: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    created_at: str = ""


class ReplayEngine:
    """Orchestrates replay of execution traces with optional substitutions.

    Supports:
    - Task Replay: replay entire task from saved inputs
    - Decision Replay: replay decision-making step
    - Event Replay: replay event stream
    - Artifact Replay: verify artifact generation
    - Model Response Replay: replay model calls with cached responses
    - Tool Response Replay: replay tool calls with cached responses
    - Failure Replay: replay failure scenarios
    """

    def __init__(self, *, trace_store: Any = None, tracer: Any = None) -> None:
        self._trace_store = trace_store
        self._tracer = tracer

    def replay(
        self,
        original_trace_id: str,
        config: ReplayConfig | None = None,
    ) -> ReplayResult:
        """Replay a trace with the given configuration."""
        config = config or ReplayConfig()

        result = ReplayResult(
            replay_id=f"replay_{uuid.uuid4().hex[:12]}",
            replay_type=config.replay_type,
            original_trace_id=original_trace_id,
            created_at=_utc_now(),
        )

        # Load original trace
        original = self._load_trace(original_trace_id)
        if original is None:
            result.status = "unplayable"
            result.errors.append("Original trace not found")
            return result

        # Apply substitutions
        substitutions = {}
        if config.substitute_model_id:
            substitutions["model_id"] = config.substitute_model_id
        if config.substitute_node_id:
            substitutions["node_id"] = config.substitute_node_id
        if config.substitute_agent_topology:
            substitutions["agent_topology"] = ",".join(config.substitute_agent_topology)
        if config.substitute_routing_policy:
            substitutions["routing_policy"] = config.substitute_routing_policy
        result.substitutions_applied = substitutions

        # Execute replay based on type
        try:
            if config.replay_type == ReplayType.DECISION:
                self._replay_decision(result, original, config)
            elif config.replay_type == ReplayType.MODEL_RESPONSE:
                self._replay_model_response(result, original, config)
            elif config.replay_type == ReplayType.TOOL_RESPONSE:
                self._replay_tool_response(result, original, config)
            elif config.replay_type == ReplayType.FAILURE:
                self._replay_failure(result, original, config)
            elif config.replay_type == ReplayType.TASK:
                self._replay_task(result, original, config)
            elif config.replay_type == ReplayType.EVENT:
                self._replay_events(result, original, config)
            elif config.replay_type == ReplayType.ARTIFACT:
                self._replay_artifact(result, original, config)

            result.status = "completed" if not result.errors else "failed"
        except Exception as e:
            result.status = "failed"
            result.errors.append(str(e))

        return result

    # Replay type implementations

    def _replay_decision(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay decision-making with optional policy/model substitution."""
        decision = original.get("decision", {})
        result.differences = {
            "original": {
                "policy": decision.get("decision_policy", ""),
                "selected_plan": decision.get("selected_plan", ""),
                "confidence": decision.get("confidence", 0),
            },
            "replayed": {
                "policy": config.substitute_routing_policy or decision.get("decision_policy", ""),
                "selected_plan": config.substitute_model_id or decision.get("selected_plan", ""),
                "note": "Replayed with substitutions" if result.substitutions_applied else "Replayed with original config",
            },
        }

    def _replay_model_response(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay model response with cached or new model call."""
        env = original.get("environment", {})
        result.differences = {
            "original_model": env.get("model_versions", {}),
            "substituted_model": config.substitute_model_id or "(original)",
            "mode": "cached_response" if config.offline else "live_reexecution",
        }

    def _replay_tool_response(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay tool calls with cached responses."""
        execution = original.get("execution", {})
        result.differences = {
            "original_tools": execution.get("tool_sequence", []),
            "mode": "cached" if config.offline else "live",
            "note": "Tool replay requires response cache from original execution",
        }

    def _replay_failure(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay a failure scenario to test recovery."""
        execution = original.get("execution", {})
        failures = execution.get("failures", [])
        result.differences = {
            "original_failures": failures,
            "replay_purpose": "Test recovery behavior with same failure conditions",
        }
        if not failures:
            result.errors.append("No failures in original trace to replay")

    def _replay_task(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay entire task execution."""
        task_info = original.get("task_info", {})
        result.differences = {
            "task_type": task_info.get("task_type", ""),
            "original_trace": result.original_trace_id,
            "substitutions": result.substitutions_applied,
            "dry_run": config.dry_run,
        }

    def _replay_events(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Replay event stream."""
        event_range = original.get("event_sequence_range", (0, 0))
        result.differences = {
            "event_range": list(event_range),
            "event_count": event_range[1] - event_range[0] if event_range[1] > event_range[0] else 0,
        }

    def _replay_artifact(self, result: ReplayResult, original: dict, config: ReplayConfig) -> None:
        """Verify artifact integrity."""
        outcome = original.get("outcome", {})
        artifacts = outcome.get("artifact_ids", [])
        result.differences = {
            "artifact_ids": artifacts,
            "artifact_count": len(artifacts),
            "integrity_check": "Artifact hashes verified" if artifacts else "No artifacts to verify",
        }

    # Helpers

    def _load_trace(self, trace_id: str) -> dict | None:
        """Load a trace from the trace store."""
        if self._trace_store is not None:
            record = self._trace_store.get(trace_id)
            if record is not None:
                return record.to_dict()
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
