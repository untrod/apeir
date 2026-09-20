# -*- coding: utf-8 -*-
"""Enhanced Execution Trace — versioned, comprehensive task traces.

This module extends the existing `nous_runtime.execution.trace` with:
- Full task/environment/decision/execution/outcome field capture
- JSONL + SQLite dual persistence
- Schema migration and anonymization
- Auto-building from EventEnvelope + ExecutionTrace + DecisionRecord
- Export and deletion support

Public API:
    ExecutionTraceRecord  — the comprehensive trace dataclass
    TraceCollector        — builds traces from runtime events
    TraceStore            — JSONL + SQLite persistence
"""

from .schema import ExecutionTraceRecord, TraceTaskInfo, TraceEnvironment, TraceDecision, TraceExecution, TraceOutcome
from .collector import TraceCollector
from .store import TraceStore

__all__ = [
    "ExecutionTraceRecord",
    "TraceTaskInfo",
    "TraceEnvironment",
    "TraceDecision",
    "TraceExecution",
    "TraceOutcome",
    "TraceCollector",
    "TraceStore",
]
