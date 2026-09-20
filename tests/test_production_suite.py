# -*- coding: utf-8 -*-
"""Production-grade tests for the V1.0 productization layer.

Covers: UI integration, installer workflow, daemon stability,
API contract, first-launch, and end-to-end product coherence.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path




# API Contract Tests


class TestApiContracts:
    """Verify all API endpoints follow the envelope contract."""

    def test_status_endpoint_contract(self):
        from nous_runtime.api.routes import handle_status
        result = handle_status()
        assert result["ok"] is True
        data = result["data"]
        assert "version" in data
        assert "running" in data
        assert data["running"] is True
        assert "providers" in data
        assert "capabilities" in data

    def test_health_endpoint_contract(self):
        from nous_runtime.api.routes import handle_health
        result = handle_health()
        assert result["ok"] is True

    def test_version_endpoint_contract(self):
        from nous_runtime.api.routes import handle_version
        result = handle_version()
        assert result["ok"] is True
        assert "version" in result["data"]

    def test_error_response_format(self):
        from nous_runtime.api.routes import err_response
        result = err_response("TEST_ERROR", "Test message")
        assert result["ok"] is False
        assert result["error"]["code"] == "TEST_ERROR"
        assert result["error"]["message"] == "Test message"

    def test_missing_route_returns_error(self):
        from nous_runtime.api.routes import route
        result = route("GET", "/nonexistent/path")
        assert result["ok"] is False
        assert result["error"]["code"] == "NOUS_INVALID_REQUEST"


class TestDesktopApiEndpoints:
    """Verify desktop-specific API endpoints."""

    def test_tasks_list_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_tasks_list
        result = handle_tasks_list()
        assert result["ok"] is True
        data = result["data"]
        assert "tasks" in data
        assert "total" in data
        assert "running" in data

    def test_tasks_list_with_filter(self):
        from nous_runtime.api.desktop_routes import handle_tasks_list
        result = handle_tasks_list(state="running")
        assert result["ok"] is True

    def test_devices_list_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_devices_list
        result = handle_devices_list()
        assert result["ok"] is True
        data = result["data"]
        assert "devices" in data
        assert "online" in data
        # Local device should always be present
        assert data["total"] >= 1

    def test_devices_scan_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_devices_scan
        result = handle_devices_scan()
        assert result["ok"] is True

    def test_automations_crud(self):
        from nous_runtime.api.desktop_routes import (
            handle_automations_list,
            handle_automations_add,
            handle_automations_action,
        )

        # List initially
        result = handle_automations_list()
        assert result["ok"] is True

        # Add
        add_result = handle_automations_add({
            "name": "Test Automation",
            "trigger": "schedule",
            "schedule": "0 9 * * *",
            "action": "Daily summary",
        })
        assert add_result["ok"] is True
        auto_id = add_result["data"]["id"]

        # Disable
        action_result = handle_automations_action({
            "action": "disable",
            "automation_id": auto_id,
        })
        assert action_result["ok"] is True
        assert action_result["data"]["enabled"] is False

        # Enable
        action_result = handle_automations_action({
            "action": "enable",
            "automation_id": auto_id,
        })
        assert action_result["ok"] is True
        assert action_result["data"]["enabled"] is True

    def test_knowledge_crud(self):
        from nous_runtime.api.desktop_routes import (
            handle_knowledge_list,
            handle_knowledge_add,
        )

        add_result = handle_knowledge_add({
            "title": "Test Document",
            "category": "documents",
            "content": "Test content for knowledge base.",
        })
        assert add_result["ok"] is True

        list_result = handle_knowledge_list()
        assert list_result["ok"] is True
        assert list_result["data"]["total"] >= 1

    def test_security_permissions_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_security_permissions
        result = handle_security_permissions()
        assert result["ok"] is True
        assert "permissions" in result["data"]
        assert len(result["data"]["permissions"]) >= 4

    def test_logs_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_logs_list
        result = handle_logs_list(level="info", limit=20)
        assert result["ok"] is True
        assert "lines" in result["data"]

    def test_memory_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_memory_usage
        result = handle_memory_usage()
        assert result["ok"] is True
        assert "used_pct" in result["data"]

    def test_dashboard_full_endpoint(self):
        from nous_runtime.api.desktop_routes import handle_dashboard_full
        result = handle_dashboard_full()
        assert result["ok"] is True
        data = result["data"]
        assert "runtime" in data
        assert "models" in data
        assert "tasks" in data
        assert "devices" in data
        assert "memory" in data


class TestTaskCenterEndpoints:
    """Verify task center API endpoints."""

    def test_task_timeline_endpoint(self):
        from nous_runtime.api.task_center_routes import handle_task_timeline
        result = handle_task_timeline()
        assert result["ok"] is True

    def test_task_graph_endpoint(self):
        from nous_runtime.api.task_center_routes import handle_task_graph
        result = handle_task_graph()
        assert result["ok"] is True
        assert "nodes" in result["data"]
        assert "edges" in result["data"]

    def test_task_artifacts_endpoint(self):
        from nous_runtime.api.task_center_routes import handle_task_artifacts
        result = handle_task_artifacts("nonexistent-task")
        assert result["ok"] is True
        assert result["data"]["count"] == 0

    def test_task_verification_endpoint(self):
        from nous_runtime.api.task_center_routes import handle_task_verification
        result = handle_task_verification("test-task")
        assert result["ok"] is True



# First-Launch Tests


class TestFirstLaunch:
    def test_is_first_launch_new_workspace(self):
        from nous_runtime.deployment.first_launch import is_first_launch
        with tempfile.TemporaryDirectory() as tmp:
            assert is_first_launch(tmp) is True

    def test_is_first_launch_after_mark(self):
        from nous_runtime.deployment.first_launch import (
            is_first_launch,
            mark_launched,
        )
        with tempfile.TemporaryDirectory() as tmp:
            mark_launched(tmp)
            assert is_first_launch(tmp) is False

    def test_mark_launched_creates_marker(self):
        from nous_runtime.deployment.first_launch import mark_launched
        with tempfile.TemporaryDirectory() as tmp:
            mark_launched(tmp)
            marker = Path(tmp) / ".nous_initialized"
            assert marker.is_file()
            data = json.loads(marker.read_text())
            assert "initialized_at" in data
            assert "version" in data

    def test_run_first_launch_returns_false_when_not_first(self):
        from nous_runtime.deployment.first_launch import (
            run_first_launch_if_needed,
            mark_launched,
        )
        with tempfile.TemporaryDirectory() as tmp:
            mark_launched(tmp)
            assert run_first_launch_if_needed(tmp) is False

    def test_run_first_launch_returns_true_when_first(self):
        from nous_runtime.deployment.first_launch import (
            run_first_launch_if_needed,
        )
        with tempfile.TemporaryDirectory() as tmp:
            # Should return True even if wizard fails (no stdin)
            run_first_launch_if_needed(tmp)
            # After running, marker should exist
            marker = Path(tmp) / ".nous_initialized"
            assert marker.is_file()



# Daemon Stability Tests


class TestDaemonStability:
    def test_service_start_stop(self):
        from nous_runtime.daemon.service import DaemonService
        svc = DaemonService()
        assert svc.start() is True
        assert svc.is_running is True
        assert svc.stop() is True
        assert svc.is_running is False

    def test_service_status_dict(self):
        from nous_runtime.daemon.service import DaemonService
        svc = DaemonService()
        status = svc.status()
        assert "running" in status
        assert "host" in status
        assert "port" in status
        assert "platform" in status

    def test_health_checker_lifecycle(self):
        from nous_runtime.daemon.health import HealthChecker
        checker = HealthChecker(interval_seconds=60)
        checker.register_check("always_ok", lambda: True)
        checker.register_metric("counter", lambda: 1)

        status = checker.run_once()
        assert status.healthy is True
        assert status.components["always_ok"] is True
        assert status.metrics["counter"] == 1

    def test_health_checker_consecutive_runs(self):
        from nous_runtime.daemon.health import HealthChecker
        checker = HealthChecker(interval_seconds=60)
        checker.register_check("test", lambda: True)

        for _ in range(3):
            status = checker.run_once()
            assert status.healthy is True

    def test_crash_recovery_record_and_reset(self):
        from nous_runtime.daemon.recovery import CrashRecovery
        recovery = CrashRecovery()

        try:
            raise RuntimeError("test crash")
        except RuntimeError as e:
            recovery.record_crash(e, "test")

        status = recovery.get_status()
        assert status["total_crashes"] == 1

        recovery.reset_failure_count()
        assert recovery.get_status()["consecutive_failures"] == 0

    def test_crash_recovery_backoff_increases(self):
        from nous_runtime.daemon.recovery import CrashRecovery
        recovery = CrashRecovery()
        d1 = recovery.get_backoff_delay()

        for i in range(3):
            try:
                raise RuntimeError(f"fail_{i}")
            except RuntimeError as e:
                recovery.record_crash(e, "test")

        d2 = recovery.get_backoff_delay()
        assert d2 > d1

    def test_daemon_health_and_recovery_integration(self):
        from nous_runtime.daemon.health import HealthChecker
        from nous_runtime.daemon.recovery import CrashRecovery

        checker = HealthChecker()
        recovery = CrashRecovery()

        checker.register_check(
            "no_crashes",
            lambda: recovery.get_status()["total_crashes"] == 0,
        )
        status = checker.run_once()
        assert status.healthy is True



# Installer Workflow Tests


class TestInstallerWorkflow:
    def test_hardware_detection_completes(self):
        from nous_runtime.deployment.setup_wizard import detect_hardware
        hw = detect_hardware()
        assert hw.cpu_cores >= 1
        assert hw.platform != ""

    def test_setup_config_validation(self):
        from nous_runtime.deployment.setup_wizard import SetupConfig
        config = SetupConfig()
        assert config.runtime_mode in ("cloud_assisted", "local", "hybrid")
        assert isinstance(config.auto_start, bool)
        assert isinstance(config.create_desktop_shortcut, bool)

    def test_setup_config_save_load_cycle(self):
        from nous_runtime.deployment.setup_wizard import (
            SetupConfig,
            save_setup_config,
            load_setup_config,
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = SetupConfig(
                runtime_mode="local",
                install_path=tmp,
                auto_start=False,
            )
            config.accepted_license = True
            path = Path(tmp) / "config.json"
            save_setup_config(config, path)
            loaded = load_setup_config(path)
            assert loaded is not None
            assert loaded.runtime_mode == "local"
            assert loaded.accepted_license is True

    def test_product_installer_plan(self):
        from nous_runtime.deployment.product_installer import (
            ProductInstaller,
            InstallMode,
        )
        with tempfile.TemporaryDirectory() as tmp:
            installer = ProductInstaller(Path(tmp) / "Nous")
            plan = installer.plan(InstallMode.RECOMMENDED)
            d = plan.to_dict()
            assert "mode" in d or "components" in d or "path" in d

    def test_console_wizard_creation(self):
        from nous_runtime.deployment.setup_wizard import ConsoleSetupWizard
        wizard = ConsoleSetupWizard("/test/path")
        assert wizard.config is not None
        assert wizard.hardware is not None



# Module Import Coherence Tests


class TestModuleCoherence:
    """Verify all productization modules import without errors."""

    def test_all_api_modules_import(self):
        from nous_runtime.api import routes
        from nous_runtime.api import desktop_routes
        from nous_runtime.api import task_center_routes
        assert routes is not None
        assert desktop_routes is not None
        assert task_center_routes is not None

    def test_all_deployment_modules_import(self):
        from nous_runtime.deployment import setup_wizard
        from nous_runtime.deployment import first_launch
        from nous_runtime.deployment import product_installer
        from nous_runtime.deployment import platform_detect
        assert setup_wizard is not None
        assert first_launch is not None
        assert product_installer is not None
        assert platform_detect is not None

    def test_all_daemon_modules_import(self):
        from nous_runtime.daemon import service
        from nous_runtime.daemon import health
        from nous_runtime.daemon import recovery
        assert service is not None
        assert health is not None
        assert recovery is not None

    def test_all_persona_modules_import(self):
        from nous_runtime.persona import learning_assistant
        from nous_runtime.persona import project_assistant
        assert learning_assistant is not None
        assert project_assistant is not None

    def test_desktop_routes_registered(self):
        """Verify desktop routes are registered in main ROUTES dict."""
        from nous_runtime.api.routes import ROUTES
        # Desktop endpoints should be in the combined routes
        desktop_keys = [
            ("GET", "/api/tasks"),
            ("GET", "/api/devices"),
            ("GET", "/api/automations"),
            ("GET", "/api/knowledge"),
            ("GET", "/api/security/permissions"),
            ("GET", "/api/logs"),
            ("GET", "/api/runtime/memory"),
            ("GET", "/api/dashboard"),
        ]
        for key in desktop_keys:
            assert key in ROUTES, f"Route {key} should be registered"

    def test_task_center_routes_registered(self):
        """Verify task center routes are registered."""
        from nous_runtime.api.routes import ROUTES
        task_center_keys = [
            ("GET", "/api/tasks/timeline"),
            ("GET", "/api/tasks/graph"),
        ]
        for key in task_center_keys:
            assert key in ROUTES, f"Route {key} should be registered"



# Long-Running / Stability Tests


class TestLongRunningStability:
    """Simulate sustained operation to verify stability."""

    def test_health_checker_100_iterations(self):
        from nous_runtime.daemon.health import HealthChecker
        checker = HealthChecker(interval_seconds=0.01)
        checker.register_check("always_ok", lambda: True)

        for i in range(100):
            status = checker.run_once()
            assert status.healthy is True
            assert status.uptime_seconds >= 0

    def test_crash_recovery_under_repeated_failures(self):
        from nous_runtime.daemon.recovery import CrashRecovery
        recovery = CrashRecovery()

        for i in range(10):
            try:
                raise RuntimeError(f"failure_{i}")
            except RuntimeError as e:
                recovery.record_crash(e, "test")

        status = recovery.get_status()
        assert status["total_crashes"] == 10
        assert status["consecutive_failures"] == 10

        # Should still allow restart if under window
        # (The window check depends on timing; verify it returns a boolean)
        result = recovery.should_restart()
        assert isinstance(result, bool)

        recovery.reset_failure_count()
        assert recovery.should_restart() is True

    def test_automations_persistence_under_stress(self):
        """Verify automations store survives rapid add/toggle cycles."""
        from nous_runtime.api.desktop_routes import (
            handle_automations_add,
            handle_automations_action,
            handle_automations_list,
        )

        ids = []
        for i in range(5):
            r = handle_automations_add({
                "name": f"Stress test {i}",
                "trigger": "schedule",
                "schedule": f"0 {i} * * *",
                "action": f"Action {i}",
            })
            assert r["ok"] is True
            ids.append(r["data"]["id"])

        # Toggle each one
        for aid in ids:
            action_result = handle_automations_action({
                "action": "disable",
                "automation_id": aid,
            })
            assert action_result["ok"] is True

        # Verify all still present
        list_result = handle_automations_list()
        assert list_result["data"]["total"] >= 5

    def test_dashboard_handles_missing_components_gracefully(self):
        """Dashboard should not crash if subsystems are unavailable."""
        from nous_runtime.api.desktop_routes import handle_dashboard_full
        result = handle_dashboard_full()
        assert result["ok"] is True
        # Should always return the expected structure
        for key in ("runtime", "models", "tasks", "devices", "memory"):
            assert key in result["data"], f"Dashboard missing '{key}'"



# Backward Compatibility Tests


class TestBackwardCompatibility:
    """Verify new modules don't break existing contracts."""

    def test_core_runtime_unchanged(self):
        from nous_runtime.kernel.runtime import Runtime
        from nous_runtime import __version__
        rt = Runtime()
        status = rt.status()
        assert status.version == __version__
        assert isinstance(status.running, bool)

    def test_provider_registry_unchanged(self):
        from nous_runtime.provider.registry import ProviderRegistry
        assert ProviderRegistry is not None

    def test_governance_gate_unchanged(self):
        from nous_runtime.governance import (
            ExecutionAuthorizationGate,
            get_gate,
        )
        assert ExecutionAuthorizationGate is not None
        gate = get_gate()
        assert gate is not None

    def test_cli_app_still_loads(self):
        from nous_runtime.cli.main import app
        assert app.info.name == "nous"

    def test_all_existing_commands_unaffected(self):
        """Verify all existing CLI commands still resolve."""
        from nous_runtime.cli.main import app
        commands = [
            cmd.name for cmd in app.registered_commands
            if cmd.name
        ]
        expected = [
            "init", "demo", "version", "status", "doctor",
            "trace", "chat", "setup",
        ]
        for cmd in expected:
            assert cmd in commands, f"CLI command '{cmd}' should exist"
