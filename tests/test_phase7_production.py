# -*- coding: utf-8 -*-
"""Tests for Phase 7 — Production Runtime."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from nous_runtime.container.docker_config import (
    generate_docker_compose,
    generate_dockerfile,
)
from nous_runtime.daemon.lifecycle import DaemonLifecycle, DaemonState
from nous_runtime.daemon.shutdown import graceful_shutdown
from nous_runtime.daemon.supervisor import ProcessSupervisor
from nous_runtime.deployment.platform_detect import PlatformInfo, detect_platform
from nous_runtime.monitoring.health import HealthChecker
from nous_runtime.monitoring.metrics import MetricsCollector, RuntimeMetrics
from nous_runtime.operations.node_manager import NodeManager
from nous_runtime.operations.release import ReleaseChecklist
from nous_runtime.operations.security_hardening import SecurityHardening
from nous_runtime.platform.adapter import PlatformAdapter, get_platform_adapter
from nous_runtime.update.manager import UpdateManager


class TestDaemonLifecycle:
    def test_initial_state(self):
        lc = DaemonLifecycle()
        assert lc.state == DaemonState.STOPPED

    def test_valid_transition(self):
        lc = DaemonLifecycle()
        assert lc.transition(DaemonState.STARTING) is True
        assert lc.state == DaemonState.STARTING

    def test_invalid_transition(self):
        lc = DaemonLifecycle()
        assert lc.transition(DaemonState.RUNNING) is False

    def test_crash_recovery(self):
        lc = DaemonLifecycle()
        lc.transition(DaemonState.STARTING)
        lc.transition(DaemonState.CRASHED)
        assert lc.should_auto_restart() is True

    def test_status(self):
        lc = DaemonLifecycle()
        s = lc.status()
        assert s["state"] == "stopped"


class TestProcessSupervisor:
    def test_create(self):
        sup = ProcessSupervisor(check_fn=lambda: True, check_interval_sec=99.0)
        assert sup._interval == 99.0

    def test_check_now_healthy(self):
        sup = ProcessSupervisor(check_fn=lambda: True)
        assert sup.check_now() is True

    def test_check_now_unhealthy(self):
        sup = ProcessSupervisor(check_fn=lambda: False)
        assert sup.check_now() is False


class TestPlatformDetect:
    def test_detect_returns_info(self):
        info = detect_platform()
        assert isinstance(info, PlatformInfo)
        assert info.os_name != ""

    def test_platform_info_to_dict(self):
        info = detect_platform()
        d = info.to_dict()
        assert "os" in d
        assert "python" in d


class TestPlatformAdapter:
    def test_get_adapter(self):
        adapter = get_platform_adapter()
        assert isinstance(adapter, PlatformAdapter)

    def test_capabilities(self):
        adapter = PlatformAdapter()
        caps = adapter.capabilities
        assert caps.os_name != ""
        assert caps.mode in ("cpu", "gpu", "jetson", "edge")

    def test_to_dict(self):
        d = PlatformAdapter().to_dict()
        assert "os" in d


class TestMetricsCollector:
    def test_collect(self):
        mc = MetricsCollector()
        m = mc.collect()
        assert isinstance(m, RuntimeMetrics)
        assert m.uptime_seconds >= 0

    def test_snapshot(self):
        s = MetricsCollector().snapshot()
        assert "timestamp" in s


class TestHealthChecker:
    def test_check_all(self):
        result = HealthChecker.check_all()
        assert "healthy" in result
        assert "components" in result


class TestDockerConfig:
    def test_generate_compose(self):
        yml = generate_docker_compose()
        assert "nous-runtime" in yml
        assert "9770" in yml

    def test_generate_dockerfile(self):
        df = generate_dockerfile()
        assert "FROM python" in df
        assert "nous_runtime" in df

    def test_custom_port(self):
        yml = generate_docker_compose(port=9999)
        assert "9999:9770" in yml


class TestUpdateManager:
    def test_current_version(self):
        um = UpdateManager()
        assert um.current_version() != ""

    def test_get_history(self):
        um = UpdateManager()
        assert isinstance(um.get_history(), list)


class TestNodeManager:
    def test_summary(self):
        nm = NodeManager()
        s = nm.summary()
        assert "total" in s
        assert "online" in s


class TestSecurityHardening:
    def test_audit(self):
        result = SecurityHardening.audit()
        assert "high_issues" in result
        assert "findings" in result


class TestReleaseChecklist:
    def test_validate(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0),
        )
        result = ReleaseChecklist.validate()
        assert "release_ready" in result
        assert "checks" in result
        assert "tests" in result["checks"]


class TestShutdown:
    def test_graceful_shutdown(self):
        report = graceful_shutdown()
        assert isinstance(report, dict)
        assert "success" in report
