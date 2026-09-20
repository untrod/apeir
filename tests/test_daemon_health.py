# -*- coding: utf-8 -*-
"""Tests for the daemon health check and recovery modules."""

from __future__ import annotations

import tempfile


from nous_runtime.daemon.health import (
    HealthStatus,
    HealthChecker,
    create_default_checks,
)
from nous_runtime.daemon.recovery import (
    CrashRecord,
    CrashRecovery,
    create_default_recovery,
)


class TestHealthStatus:
    def test_default_healthy(self):
        status = HealthStatus()
        assert status.healthy is True
        assert status.components == {}
        assert status.errors == []

    def test_to_dict(self):
        status = HealthStatus(
            healthy=False,
            components={"runtime": True, "database": False},
            errors=["database connection failed"],
        )
        d = status.to_dict()
        assert d["healthy"] is False
        assert d["components"]["database"] is False
        assert len(d["errors"]) == 1

    def test_errors_truncated(self):
        status = HealthStatus()
        status.errors = [f"error_{i}" for i in range(20)]
        d = status.to_dict()
        assert len(d["errors"]) <= 10


class TestHealthChecker:
    def test_register_check(self):
        checker = HealthChecker(interval_seconds=60)
        checker.register_check("test_check", lambda: True)
        assert "test_check" in checker._checks

    def test_register_metric(self):
        checker = HealthChecker(interval_seconds=60)
        checker.register_metric("test_metric", lambda: 42)
        assert "test_metric" in checker._metric_collectors

    def test_run_once_all_healthy(self):
        checker = HealthChecker(interval_seconds=60)
        checker.register_check("check_a", lambda: True)
        checker.register_check("check_b", lambda: True)
        checker.register_metric("metric_a", lambda: 100)

        status = checker.run_once()
        assert status.healthy is True
        assert status.components["check_a"] is True
        assert status.components["check_b"] is True
        assert status.metrics["metric_a"] == 100
        assert status.last_check != ""
        assert status.uptime_seconds >= 0

    def test_run_one_failing(self):
        checker = HealthChecker(interval_seconds=60)
        checker.register_check("good", lambda: True)
        checker.register_check("bad", lambda: False)

        status = checker.run_once()
        assert status.healthy is False
        assert status.components["good"] is True
        assert status.components["bad"] is False
        assert len(status.errors) >= 1

    def test_run_check_raises_exception(self):
        checker = HealthChecker(interval_seconds=60)
        def raise_error():
            raise RuntimeError("boom")
        checker.register_check("crashy", raise_error)

        status = checker.run_once()
        assert status.healthy is False
        assert status.components["crashy"] is False
        assert any("crashy" in e for e in status.errors)

    def test_metric_collector_raises(self):
        checker = HealthChecker(interval_seconds=60)
        def raise_error():
            raise RuntimeError("metric error")
        checker.register_metric("bad_metric", raise_error)

        status = checker.run_once()
        assert "collection_error" in str(status.metrics["bad_metric"])


class TestCreateDefaultChecks:
    def test_creates_with_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker = create_default_checks(workspace=tmp)
            assert len(checker._checks) >= 2
            assert len(checker._metric_collectors) >= 1

            status = checker.run_once()
            # Workspace check should pass (it creates the directory)
            assert status.components.get("workspace", True) is True


class TestCrashRecord:
    def test_create_record(self):
        record = CrashRecord(
            timestamp="2026-07-27T00:00:00Z",
            error_type="RuntimeError",
            error_message="test error",
            component="runtime",
        )
        d = record.to_dict()
        assert d["error_type"] == "RuntimeError"
        assert d["component"] == "runtime"
        assert d["recovered"] is False

    def test_recovered_record(self):
        record = CrashRecord(
            error_type="ValueError",
            error_message="test",
            component="database",
            recovered=True,
        )
        assert record.recovered is True


class TestCrashRecovery:
    def test_register_handler(self):
        recovery = CrashRecovery()
        recovery.register_handler("runtime", lambda: None)
        assert "runtime" in recovery._recovery_handlers

    def test_record_crash(self):
        recovery = CrashRecovery()
        try:
            raise ValueError("test crash")
        except ValueError as e:
            record = recovery.record_crash(e, "runtime")

        assert record.error_type == "ValueError"
        assert record.component == "runtime"
        assert record.recovered is False  # No handler registered

    def test_record_crash_with_handler(self):
        recovery = CrashRecovery()
        recovered_flag = []

        def recover():
            recovered_flag.append(True)

        recovery.register_handler("runtime", recover)
        try:
            raise RuntimeError("recoverable")
        except RuntimeError as e:
            record = recovery.record_crash(e, "runtime")

        assert record.error_type == "RuntimeError"
        assert record.recovered is True
        assert recovered_flag == [True]

    def test_should_restart_initial(self):
        recovery = CrashRecovery()
        assert recovery.should_restart() is True

    def test_should_restart_within_limit(self):
        recovery = CrashRecovery()
        for _ in range(3):
            try:
                raise RuntimeError("test")
            except RuntimeError as e:
                recovery.record_crash(e, "runtime")
        assert recovery.should_restart() is True

    def test_get_backoff_delay(self):
        recovery = CrashRecovery()
        delay0 = recovery.get_backoff_delay()
        assert delay0 >= recovery.INITIAL_BACKOFF

        # Simulate consecutive failures
        for i in range(3):
            try:
                raise RuntimeError(f"fail_{i}")
            except RuntimeError as e:
                recovery.record_crash(e, "runtime")

        delay3 = recovery.get_backoff_delay()
        assert delay3 >= delay0  # Should increase

    def test_reset_failure_count(self):
        recovery = CrashRecovery()
        try:
            raise RuntimeError("test")
        except RuntimeError as e:
            recovery.record_crash(e, "runtime")
        assert recovery._consecutive_failures > 0

        recovery.reset_failure_count()
        assert recovery._consecutive_failures == 0

    def test_get_status(self):
        recovery = CrashRecovery()
        status = recovery.get_status()
        assert "consecutive_failures" in status
        assert "total_crashes" in status
        assert "registered_handlers" in status

    def test_get_crash_history(self):
        recovery = CrashRecovery()
        for i in range(3):
            try:
                raise RuntimeError(f"error_{i}")
            except RuntimeError as e:
                recovery.record_crash(e, "runtime")
        history = recovery.get_crash_history(limit=2)
        assert len(history) <= 2


class TestCreateDefaultRecovery:
    def test_creates_with_handlers(self):
        recovery = create_default_recovery()
        assert "runtime" in recovery._recovery_handlers
        assert "database" in recovery._recovery_handlers
        assert "providers" in recovery._recovery_handlers

    def test_recover_runtime_handler(self):
        recovery = create_default_recovery()
        handler = recovery._recovery_handlers.get("runtime")
        assert handler is not None
        # Handler should be callable
        assert callable(handler)
