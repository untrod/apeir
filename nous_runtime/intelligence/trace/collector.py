# -*- coding: utf-8 -*-
"""TraceCollector — builds ExecutionTraceRecord from runtime data sources.

Bridges existing infrastructure (ExecutionTracer, EventEnvelope, DecisionRecord,
SchedulingResult, profiles) into the comprehensive ExecutionTraceRecord format.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .schema import (
    ExecutionTraceRecord,
)

_log = logging.getLogger("nous.trace.collector")


class TraceCollector:
    """Assembles ExecutionTraceRecord from runtime components.

    Uses whatever data sources are available — fills in what it can,
    leaves unknowns as default values. Never throws on missing data.

    Usage:
        collector = TraceCollector()
        record = collector.collect(
            tracer=execution_tracer,
            trace_id="trace_abc",
            decision_record=decision,
            scheduling_result=sched_result,
        )
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._lock = threading.Lock()

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def collect(
        self,
        *,
        trace_id: str = "",
        session_id: str = "",
        # Existing trace infrastructure
        tracer: Any = None,             # ExecutionTracer instance
        # Decision infrastructure
        decision_record: Any = None,    # DecisionRecord from intelligence
        scheduling_result: Any = None,  # SchedulingResult from scheduler
        routing_decision: Any = None,   # RoutingDecision from routing
        # Additional context
        task_analysis: Any = None,      # TaskAnalysis from task analyzer
        environment_override: dict | None = None,
        outcome_override: dict | None = None,
        # Feature flags
        sanitization_level: str = "basic",
    ) -> ExecutionTraceRecord:
        """Build a comprehensive trace record from available sources."""

        record = ExecutionTraceRecord.new(
            task_id="",
            session_id=session_id,
            sequence=self.next_sequence(),
        )
        if trace_id:
            record.trace_id = trace_id
        record.sanitization_level = sanitization_level

        # Fill from ExecutionTracer
        if tracer is not None:
            self._fill_from_tracer(record, tracer, trace_id)

        # Fill from DecisionRecord
        if decision_record is not None:
            self._fill_from_decision(record, decision_record)

        # Fill from SchedulingResult
        if scheduling_result is not None:
            self._fill_from_scheduling(record, scheduling_result)

        # Fill from RoutingDecision
        if routing_decision is not None:
            self._fill_from_routing(record, routing_decision)

        # Fill from TaskAnalysis
        if task_analysis is not None:
            self._fill_from_task_analysis(record, task_analysis)

        # Overrides
        if environment_override:
            for k, v in environment_override.items():
                if hasattr(record.environment, k):
                    setattr(record.environment, k, v)
        if outcome_override:
            for k, v in outcome_override.items():
                if hasattr(record.outcome, k):
                    setattr(record.outcome, k, v)

        record.seal()
        return record

    # Internal fillers

    def _fill_from_tracer(
        self,
        record: ExecutionTraceRecord,
        tracer: Any,
        trace_id: str,
    ) -> None:
        """Extract data from ExecutionTracer and existing TraceSpans."""
        try:
            exec_trace = tracer.get_trace(trace_id) if trace_id else None
        except Exception:
            exec_trace = None

        if exec_trace is None:
            return

        record.session_id = record.session_id or exec_trace.session_id
        record.task_info.task_id = record.task_info.task_id or exec_trace.task_id

        # Span statistics
        spans = getattr(exec_trace, "spans", [])
        record.execution.retries = sum(
            1 for s in spans if getattr(s, "retry_count", 0) > 0
        )
        record.execution.replans = sum(
            1 for s in spans
            if getattr(s, "span_kind", None) is not None
            and str(getattr(s, "span_kind", "")) == "plan"
        )

        # Model assignments from model spans
        model_spans = [
            s for s in spans
            if getattr(s, "span_kind", None) is not None
            and str(getattr(s, "span_kind", "")) == "model"
        ]
        for s in model_spans:
            mid = getattr(s, "model_id", "")
            if mid:
                role = getattr(s, "span_name", "") or mid
                record.execution.model_assignments[role] = mid

        # Node assignments from node spans
        node_spans = [
            s for s in spans
            if getattr(s, "span_kind", None) is not None
            and str(getattr(s, "span_kind", "")) == "node"
        ]
        for s in node_spans:
            nid = getattr(s, "node_id", "")
            if nid:
                role = "primary" if not record.execution.node_assignments else f"node_{len(record.execution.node_assignments)}"
                record.execution.node_assignments[role] = nid

        # Tool sequence from capability spans
        cap_spans = sorted(
            [s for s in spans
             if getattr(s, "span_kind", None) is not None
             and str(getattr(s, "span_kind", "")) == "capability"],
            key=lambda s: getattr(s, "started_at", ""),
        )
        record.execution.tool_sequence = [
            getattr(s, "capability_id", "") or getattr(s, "span_name", "")
            for s in cap_spans
        ]

        # Cost and tokens
        record.outcome.token_usage = {
            "total": sum(getattr(s, "token_usage", {}).get("total", 0) for s in spans),
            "input": sum(getattr(s, "token_usage", {}).get("input", 0) for s in spans),
            "output": sum(getattr(s, "token_usage", {}).get("output", 0) for s in spans),
        }
        record.outcome.cost_usd = sum(getattr(s, "cost_usd", 0.0) for s in spans)
        record.outcome.latency_ms = getattr(exec_trace, "total_duration_ms", 0.0)

        # Failures from failed spans
        failed = [s for s in spans if getattr(s, "status", None) is not None and str(getattr(s, "status", "")) == "failed"]
        record.execution.failures = [
            getattr(s, "error_category", "") or getattr(s, "error_message", "")[:80]
            for s in failed
        ]

        # Verification spans
        verif_spans = [
            s for s in spans
            if getattr(s, "span_kind", None) is not None
            and str(getattr(s, "span_kind", "")) == "verification"
        ]
        if verif_spans:
            all_pass = all(
                getattr(s, "status", None) is not None
                and str(getattr(s, "status", "")) == "completed"
                for s in verif_spans
            )
            any_fail = any(
                getattr(s, "status", None) is not None
                and str(getattr(s, "status", "")) == "failed"
                for s in verif_spans
            )
            record.outcome.verification_status = (
                "fail" if any_fail else ("pass" if all_pass else "warning")
            )

        # Overall status
        if exec_trace.has_errors:
            record.outcome.final_status = "failure"
        else:
            record.outcome.final_status = "success"

    def _fill_from_decision(self, record: ExecutionTraceRecord, dr: Any) -> None:
        """Extract from DecisionRecord."""
        record.decision.decision_policy = str(getattr(dr, "policy_id", ""))
        record.decision.decision_policy_version = str(getattr(dr, "policy_version", ""))
        record.decision.confidence = float(getattr(dr, "confidence", 0.0))

        # Trace decision candidates from the record
        candidates = getattr(dr, "candidates", None) or []
        record.decision.candidate_plans = len(candidates)
        record.decision.selected_plan = str(getattr(dr, "selected_candidate_id", ""))

        # Rejection reasons from candidate evaluation
        for c in candidates:
            cid = str(getattr(c, "candidate_id", ""))
            rejected = getattr(c, "rejected", False)
            reason = str(getattr(c, "rejection_reason", ""))
            if rejected and reason:
                record.decision.rejected_plans.append(cid)
                record.decision.rejection_reasons[cid] = reason

    def _fill_from_scheduling(self, record: ExecutionTraceRecord, sr: Any) -> None:
        """Extract from SchedulingResult."""
        record.decision.feasible_plans = int(getattr(sr, "feasible_count", 0))

        # Constraints from trace
        trace = getattr(sr, "trace", {}) or {}
        record.decision.hard_constraints = list(trace.get("hard_constraints", []))
        record.decision.soft_preferences = list(trace.get("soft_preferences", []))

        # Uncertainty
        record.decision.uncertainty = float(getattr(sr, "uncertainty", 0.0))

        # Checkpoint count
        record.execution.checkpoints = int(trace.get("checkpoint_count", 0))

        # Latency breakdown
        record.outcome.queue_time_ms = float(getattr(sr, "queue_time_ms", 0.0))

    def _fill_from_routing(self, record: ExecutionTraceRecord, rd: Any) -> None:
        """Extract from RoutingDecision."""
        record.decision.selected_plan = (
            record.decision.selected_plan
            or str(getattr(rd, "selected_model", ""))
        )
        # Rejected models
        rejected = getattr(rd, "rejected_models", None) or {}
        for model_id, reason in rejected.items():
            if model_id not in record.decision.rejected_plans:
                record.decision.rejected_plans.append(model_id)
            record.decision.rejection_reasons[model_id] = str(reason)
        record.decision.candidate_plans = max(
            record.decision.candidate_plans,
            int(getattr(rd, "total_candidates", 0)),
        )

    def _fill_from_task_analysis(self, record: ExecutionTraceRecord, ta: Any) -> None:
        """Extract from TaskAnalysis."""
        record.task_info.task_type = str(getattr(ta, "task_type", ""))
        record.task_info.risk_class = str(getattr(ta, "risk_level", ""))
        record.task_info.privacy_class = str(getattr(ta, "privacy_class", ""))
        record.task_info.domain = str(getattr(ta, "domain", ""))
        record.task_info.modalities = list(getattr(ta, "modalities", []))
