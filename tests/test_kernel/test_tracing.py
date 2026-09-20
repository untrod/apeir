# -*- coding: utf-8 -*-
"""Tracing and observability tests."""

from nous_runtime.kernel.tracing import (
    TraceContext,
    ExecutionTimeline,
    error_description,
    is_retryable,
    is_permanent,
    NOUS_ERROR_CODES,
)


class TestTraceContext:
    """Trace context must propagate through execution chain."""

    def test_default_trace_id(self):
        """New TraceContext generates a trace_id."""
        ctx = TraceContext()
        assert ctx.trace_id.startswith("trace_")
        assert len(ctx.trace_id) > 20

    def test_explicit_trace_id(self):
        """TraceContext accepts explicit trace_id."""
        ctx = TraceContext(trace_id="trace_test_123")
        assert ctx.trace_id == "trace_test_123"

    def test_context_has_required_fields(self):
        """TraceContext has goal/plan/task fields."""
        ctx = TraceContext(goal_id="goal_001", plan_id="plan_001")
        assert ctx.goal_id == "goal_001"
        assert ctx.plan_id == "plan_001"
        assert ctx.started_at  # auto-populated

    def test_context_manager(self):
        """TraceContext can be used as a context manager."""
        with TraceContext(trace_id="trace_test_ctx") as ctx:
            assert ctx.trace_id == "trace_test_ctx"


class TestExecutionTimeline:
    """Execution timeline must record step-by-step."""

    def test_add_entries(self):
        """Adding entries builds the timeline."""
        tl = ExecutionTimeline(trace_id="trace_test")
        tl.add("planning", capability_id="model.reason")
        tl.add("dispatching", provider_id="openai")
        tl.add("executing", duration_ms=450.0)
        tl.add("completed", ok=True)

        assert len(tl.entries) == 4
        assert tl.entries[0].step == 1
        assert tl.entries[3].step == 4

    def test_summary(self):
        """Timeline summary reports steps and failures."""
        tl = ExecutionTimeline(trace_id="trace_test")
        tl.add("planning")
        tl.add("executing", ok=True)
        tl.add("executing", ok=False, error_code="NOUS_TIMEOUT")

        s = tl.summary()
        assert s["steps"] == 3
        assert s["successes"] == 1
        assert s["failures"] == 1
        assert s["total_duration_ms"] >= 0


class TestErrorModel:
    """Error model must provide descriptions and classifications."""

    def test_all_codes_have_descriptions(self):
        """Every error code has a description."""
        for code in NOUS_ERROR_CODES:
            desc = error_description(code)
            assert desc
            assert desc != "Unknown error"

    def test_retryable_codes(self):
        """Timeout and unavailable are retryable."""
        assert is_retryable("NOUS_PROVIDER_TIMEOUT") is True
        assert is_retryable("NOUS_PROVIDER_UNAVAILABLE") is True
        assert is_retryable("NOUS_RATE_LIMITED") is True

    def test_permanent_codes(self):
        """Permission denied and policy rejected are permanent."""
        assert is_permanent("NOUS_PERMISSION_DENIED") is True
        assert is_permanent("NOUS_POLICY_REJECTED") is True

    def test_non_retryable(self):
        """Permission denied is not retryable."""
        assert is_retryable("NOUS_PERMISSION_DENIED") is False

    def test_unknown_code(self):
        """Unknown code returns generic description."""
        assert error_description("NOUS_UNKNOWN_XYZ") == "Unknown error"
