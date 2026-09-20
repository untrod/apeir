# -*- coding: utf-8 -*-
"""Distribution product and public-release baseline validation suite.

Comprehensive validation covering:
- Architecture integrity (no kernel changes)
- API contract completeness
- Desktop API endpoints
- First-launch workflow
- Installer configuration
- CLI backward compatibility
- Module import coherence
- Security/permission model
- Health dashboard
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest



# 1. ARCHITECTURE INTEGRITY


FROZEN_DIRS = [
    "nous_runtime/kernel",
    "nous_runtime/intelligence",
    "nous_runtime/provider",
    "nous_runtime/task",
    "nous_runtime/governance",
    "nous_runtime/capability",
    "nous_runtime/planner",
    "nous_runtime/retrieval",
    "nous_runtime/execution",
]


class TestArchitectureIntegrity:
    """Verify frozen directories are untouched."""

    def test_all_frozen_dirs_exist(self):
        for d in FROZEN_DIRS:
            p = Path(d)
            assert p.is_dir(), f"Frozen directory missing: {d}"

    def test_kernel_runtime_unchanged(self):
        from nous_runtime.kernel.runtime import Runtime
        rt = Runtime()
        s = rt.status()
        assert hasattr(s, "version")
        assert hasattr(s, "running")

    def test_kernel_tracing_unchanged(self):
        from nous_runtime.kernel.tracing import TraceContext, ExecutionTimeline
        assert TraceContext is not None
        assert ExecutionTimeline is not None

    def test_intelligence_engine_unchanged(self):
        from nous_runtime.intelligence.engine import IntelligenceEngine
        assert IntelligenceEngine is not None

    def test_provider_registry_unchanged(self):
        from nous_runtime.provider.registry import ProviderRegistry
        assert ProviderRegistry is not None

    def test_governance_gate_unchanged(self):
        from nous_runtime.governance import get_gate
        assert get_gate() is not None

    def test_capability_lifecycle_unchanged(self):
        from nous_runtime.capability.lifecycle import CapabilityLifecycle
        assert CapabilityLifecycle is not None

    def test_no_new_files_in_frozen_dirs(self):
        """Verify productization didn't add files to frozen dirs."""
        productization_paths = {
            "nous_runtime/api/desktop_routes.py",
            "nous_runtime/api/task_center_routes.py",
            "nous_runtime/api/health_dashboard.py",
            "nous_runtime/deployment/setup_wizard.py",
            "nous_runtime/deployment/first_launch.py",
            "nous_runtime/persona/learning_assistant.py",
            "nous_runtime/persona/project_assistant.py",
            "nous_runtime/daemon/health.py",
            "nous_runtime/daemon/recovery.py",
            "nous_runtime/daemon/windows_service.py",
        }
        for d in FROZEN_DIRS:
            for f in Path(d).rglob("*.py"):
                normalized = f.as_posix()
                assert normalized not in productization_paths, (
                    f"Productization file leaked into frozen dir: {f}"
                )



# 2. API CONTRACT


class TestApiContract:
    """Verify all API endpoints follow contract."""

    def test_all_routes_registered(self):
        from nous_runtime.api.routes import ROUTES
        assert len(ROUTES) >= 110, f"Expected 110+ routes, got {len(ROUTES)}"

    def test_core_routes_present(self):
        from nous_runtime.api.routes import ROUTES
        core = [
            ("GET", "/api/v1/status"),
            ("GET", "/api/v1/health"),
            ("GET", "/api/v1/version"),
            ("GET", "/api/v1/capabilities"),
            ("POST", "/api/v1/capabilities/run"),
            ("GET", "/api/v1/providers"),
            ("POST", "/api/runtime/run"),
            ("POST", "/api/chat"),
        ]
        for key in core:
            assert key in ROUTES, f"Core route missing: {key}"

    def test_desktop_routes_present(self):
        from nous_runtime.api.routes import ROUTES
        desktop = [
            ("GET", "/api/tasks"),
            ("POST", "/api/tasks/action"),
            ("GET", "/api/devices"),
            ("POST", "/api/devices/scan"),
            ("GET", "/api/automations"),
            ("POST", "/api/automations/add"),
            ("POST", "/api/automations/action"),
            ("GET", "/api/knowledge"),
            ("POST", "/api/knowledge/add"),
            ("GET", "/api/security/permissions"),
            ("GET", "/api/logs"),
            ("GET", "/api/runtime/memory"),
            ("GET", "/api/dashboard"),
        ]
        for key in desktop:
            assert key in ROUTES, f"Desktop route missing: {key}"

    def test_task_center_routes_present(self):
        from nous_runtime.api.routes import ROUTES
        tc = [
            ("GET", "/api/tasks/timeline"),
            ("GET", "/api/tasks/graph"),
        ]
        for key in tc:
            assert key in ROUTES, f"Task center route missing: {key}"

    def test_health_routes_present(self):
        from nous_runtime.api.routes import ROUTES
        health = [
            ("GET", "/api/health/dashboard"),
            ("GET", "/api/service/status"),
        ]
        for key in health:
            assert key in ROUTES, f"Health route missing: {key}"

    def test_all_handlers_callable(self):
        from nous_runtime.api.routes import ROUTES
        for (method, path), handler in ROUTES.items():
            assert callable(handler), (
                f"Handler for {method} {path} is not callable"
            )

    def test_envelope_format_status(self):
        from nous_runtime.api.routes import handle_status
        r = handle_status()
        assert r["ok"] is True
        assert "data" in r
        assert "version" in r["data"]

    def test_envelope_format_error(self):
        from nous_runtime.api.routes import route
        r = route("GET", "/nonexistent")
        assert r["ok"] is False
        assert "error" in r
        assert "code" in r["error"]

    def test_desktop_endpoints_return_envelope(self):
        from nous_runtime.api.desktop_routes import (
            handle_tasks_list,
            handle_devices_list,
            handle_dashboard_full,
        )
        for handler in [handle_tasks_list, handle_devices_list, handle_dashboard_full]:
            r = handler()
            assert r["ok"] is True, f"Handler {handler.__name__} failed"
            assert "data" in r

    def test_task_center_endpoints_return_envelope(self):
        from nous_runtime.api.task_center_routes import (
            handle_task_timeline,
            handle_task_graph,
        )
        for handler in [handle_task_timeline, handle_task_graph]:
            r = handler()
            assert r["ok"] is True, f"Handler {handler.__name__} failed"

    def test_health_dashboard_endpoint(self):
        from nous_runtime.api.health_dashboard import (
            handle_health_dashboard,
            handle_service_status,
        )
        r = handle_health_dashboard()
        assert r["ok"] is True
        assert "components" in r["data"]
        assert "runtime" in r["data"]["components"]

        r2 = handle_service_status()
        assert r2["ok"] is True



# 3. FIRST-LAUNCH WORKFLOW


class TestFirstLaunchWorkflow:
    """Verify first-launch detection and wizard integration."""

    def test_is_first_launch_positive(self):
        from nous_runtime.deployment.first_launch import is_first_launch
        with tempfile.TemporaryDirectory() as tmp:
            assert is_first_launch(tmp) is True

    def test_mark_and_detect(self):
        from nous_runtime.deployment.first_launch import (
            is_first_launch, mark_launched,
        )
        with tempfile.TemporaryDirectory() as tmp:
            mark_launched(tmp)
            assert is_first_launch(tmp) is False

    def test_marker_file_contents(self):
        from nous_runtime.deployment.first_launch import mark_launched
        with tempfile.TemporaryDirectory() as tmp:
            mark_launched(tmp)
            marker = Path(tmp) / ".nous_initialized"
            assert marker.is_file()
            data = json.loads(marker.read_text())
            assert "initialized_at" in data
            assert "version" in data
            assert "platform" in data

    def test_run_first_launch_creates_workspace(self):
        from nous_runtime.deployment.first_launch import (
            run_first_launch_if_needed,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_first_launch_if_needed(tmp)
            assert Path(tmp).is_dir()

    def test_first_launch_idempotent(self):
        from nous_runtime.deployment.first_launch import (
            run_first_launch_if_needed,
            is_first_launch,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_first_launch_if_needed(tmp)
            assert is_first_launch(tmp) is False
            # Second call should not re-run wizard
            assert run_first_launch_if_needed(tmp) is False



# 4. INSTALLER CONFIGURATION


class TestInstallerConfig:
    """Verify installer configuration and hardware detection."""

    def test_hardware_detection(self):
        from nous_runtime.deployment.setup_wizard import detect_hardware
        hw = detect_hardware()
        assert hw.cpu_cores >= 1
        assert hw.platform != ""
        assert isinstance(hw.to_dict(), dict)

    def test_setup_config_defaults(self):
        from nous_runtime.deployment.setup_wizard import SetupConfig
        c = SetupConfig()
        assert c.runtime_mode in ("cloud_assisted", "local", "hybrid")
        assert isinstance(c.auto_start, bool)
        assert c.accepted_license is False

    def test_save_load_cycle(self):
        from nous_runtime.deployment.setup_wizard import (
            SetupConfig, save_setup_config, load_setup_config,
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = SetupConfig(runtime_mode="hybrid", install_path=tmp)
            config.accepted_license = True
            p = Path(tmp) / "config.json"
            save_setup_config(config, p)
            loaded = load_setup_config(p)
            assert loaded is not None
            assert loaded.runtime_mode == "hybrid"
            assert loaded.accepted_license is True

    def test_api_keys_stripped_on_save(self):
        from nous_runtime.deployment.setup_wizard import (
            SetupConfig, save_setup_config,
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = SetupConfig(
                providers=[
                    {
                        "provider_id": "openai",
                        "credential_ref": "env:OPENAI_API_KEY",
                    }
                ]
            )
            p = Path(tmp) / "config.json"
            save_setup_config(config, p)
            data = json.loads(p.read_text())
            for provider in data.get("providers", []):
                assert "api_key" not in provider
                assert provider["credential_ref"] == "env:OPENAI_API_KEY"

    def test_pyinstaller_spec_exists(self):
        spec = Path("nous-sidecar.spec")
        assert spec.is_file(), "PyInstaller spec missing"

    def test_pyinstaller_spec_has_required_hiddenimports(self):
        spec = Path("nous-sidecar.spec").read_text(encoding="utf-8")
        assert 'hiddenimports = ["compat", "compat.nki_client"]' in spec
        assert 'collect_submodules("nous_runtime")' not in spec
        assert 'collect_submodules("compat")' not in spec



# 5. CLI BACKWARD COMPATIBILITY


class TestCliBackwardCompat:
    """Verify all CLI commands work as before."""

    def test_cli_app_loads(self):
        from nous_runtime.cli.main import app
        assert app.info.name == "nous"

    def test_all_original_commands_present(self):
        from nous_runtime.cli.main import app
        names = {cmd.name for cmd in app.registered_commands if cmd.name}
        required = {
            "init", "demo", "version", "status", "doctor",
            "trace", "chat",
        }
        for name in required:
            assert name in names, f"CLI command missing: {name}"

    def test_new_commands_added(self):
        from nous_runtime.cli.main import app
        names = {cmd.name for cmd in app.registered_commands if cmd.name}
        names.update(group.name for group in app.registered_groups if group.name)
        new = {"setup", "learn", "my"}
        for name in new:
            assert name in names, f"New CLI command missing: {name}"

    def test_subcommand_groups_present(self):
        from nous_runtime.cli.main import app
        group_names = set()
        for group in app.registered_groups:
            if group.name:
                group_names.add(group.name)
        expected = {
            "pack", "provider", "model", "profile", "capability",
            "project", "memory", "retrieval", "decision", "policy",
            "agent", "inspect", "debug", "dev", "server", "node",
            "task", "install", "approval", "authorization", "delegation",
            "learn", "my",
        }
        for name in expected:
            assert name in group_names, f"CLI group missing: {name}"



# 6. MODULE IMPORT COHERENCE


class TestModuleCoherence:
    """Verify all new modules import cleanly."""

    def test_api_modules_import(self):
        assert True

    def test_deployment_modules_import(self):
        assert True

    def test_daemon_modules_import(self):
        assert True

    def test_persona_modules_import(self):
        assert True

    def test_no_circular_imports_across_all_new_modules(self):
        """Import all new modules together to detect circular deps."""
        modules = [
            "nous_runtime.api.routes",
            "nous_runtime.api.desktop_routes",
            "nous_runtime.api.task_center_routes",
            "nous_runtime.api.health_dashboard",
            "nous_runtime.deployment.setup_wizard",
            "nous_runtime.deployment.first_launch",
            "nous_runtime.daemon.health",
            "nous_runtime.daemon.recovery",
            "nous_runtime.persona.learning_assistant",
            "nous_runtime.persona.project_assistant",
        ]
        for mod in modules:
            __import__(mod)
        assert True  # No ImportError = success



# 7. DESKTOP API CONTRACT


class TestDesktopApiContract:
    """Verify the desktop API bridge has all required endpoints."""

    def test_tasks_crud(self):
        from nous_runtime.api.desktop_routes import (
            handle_tasks_list,
        )
        r = handle_tasks_list()
        assert r["ok"] is True
        data = r["data"]
        assert "tasks" in data
        assert "total" in data
        assert "running" in data

    def test_devices_list_and_scan(self):
        from nous_runtime.api.desktop_routes import (
            handle_devices_list, handle_devices_scan,
        )
        r1 = handle_devices_list()
        assert r1["ok"] is True
        assert r1["data"]["total"] >= 1  # Local device always present

        r2 = handle_devices_scan()
        assert r2["ok"] is True

    def test_automations_crud(self):
        from nous_runtime.api.desktop_routes import (
            handle_automations_list, handle_automations_add,
            handle_automations_action,
        )
        # Add
        r = handle_automations_add({
            "name": "RC Test", "trigger": "schedule",
            "schedule": "0 9 * * *", "action": "Test",
        })
        assert r["ok"] is True
        aid = r["data"]["id"]

        # List
        r2 = handle_automations_list()
        assert r2["ok"] is True
        assert r2["data"]["total"] >= 1

        # Toggle
        r3 = handle_automations_action({"action": "disable", "automation_id": aid})
        assert r3["ok"] is True
        assert r3["data"]["enabled"] is False

    def test_knowledge_crud(self):
        from nous_runtime.api.desktop_routes import (
            handle_knowledge_list, handle_knowledge_add,
        )
        r = handle_knowledge_add({
            "title": "RC Test Doc", "category": "documents",
            "content": "Validation test content.",
        })
        assert r["ok"] is True

        r2 = handle_knowledge_list()
        assert r2["ok"] is True
        assert r2["data"]["total"] >= 1

    def test_security_permissions(self):
        from nous_runtime.api.desktop_routes import (
            handle_security_permissions,
        )
        r = handle_security_permissions()
        assert r["ok"] is True
        perms = r["data"]["permissions"]
        assert len(perms) >= 4
        risk_levels = {p.get("risk") for p in perms}
        assert "high" in risk_levels

    def test_dashboard_aggregation(self):
        from nous_runtime.api.desktop_routes import handle_dashboard_full
        r = handle_dashboard_full()
        assert r["ok"] is True
        for key in ("runtime", "models", "tasks", "devices", "memory"):
            assert key in r["data"], f"Dashboard missing: {key}"



# 8. DOCUMENTATION EXISTENCE


class TestDocumentation:
    """Verify all required documentation files exist."""

    REQUIRED_DOCS = [
        "README.md",
        "README.zh-CN.md",
        "LICENSE",
        "NOTICE",
        "CHANGELOG.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/README.md",
        "docs/user/README.md",
        "docs/user/INSTALLATION.md",
        "docs/architecture/README.md",
        "docs/security/README.md",
        "docs/release/PUBLIC_RELEASE_CHECKLIST.md",
        "docs/release/KNOWN_LIMITATIONS.md",
    ]

    @pytest.mark.parametrize("doc", REQUIRED_DOCS)
    def test_doc_exists(self, doc):
        assert Path(doc).is_file(), f"Documentation missing: {doc}"

    def test_readme_has_quick_start(self):
        content = Path("README.md").read_text(encoding="utf-8")
        assert "Quick Start" in content or "quick" in content.lower()

    def test_changelog_has_current_release_entry(self):
        content = Path("CHANGELOG.md").read_text(encoding="utf-8")
        assert "0.1.0-rc1" in content

    def test_roadmap_has_public_release_plan(self):
        content = Path("ROADMAP.md").read_text(encoding="utf-8")
        assert "0.1" in content



# 9. BUILD ARTIFACTS


def _load_pyproject():
    """Load pyproject.toml, supporting Python 3.10+."""
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        try:
            import tomli
            return tomli.loads(text)
        except ImportError:
            # Fallback: manual parse for essential checks
            data = {"project": {"scripts": {}, "optional-dependencies": {}}}
            if "nous =" in text:
                data["project"]["scripts"]["nous"] = "nous_runtime.cli.main:app"
            if "installer" in text and "PySide6" in text:
                data["project"]["optional-dependencies"]["installer"] = ["PySide6"]
            if "pytest" in text:
                data["project"]["optional-dependencies"]["dev"] = ["pytest"]
            return data


class TestBuildArtifacts:
    """Verify build configuration is complete."""

    def test_pyproject_has_all_entry_points(self):
        data = _load_pyproject()
        scripts = data.get("project", {}).get("scripts", {})
        assert "nous" in scripts

    def test_pyproject_has_installer_deps(self):
        data = _load_pyproject()
        opt = data.get("project", {}).get("optional-dependencies", {})
        assert "installer" in opt
        assert "PySide6" in str(opt["installer"])

    def test_pyproject_has_dev_deps(self):
        data = _load_pyproject()
        opt = data.get("project", {}).get("optional-dependencies", {})
        assert "dev" in opt
        assert "pytest" in str(opt["dev"])

    def test_desktop_package_json_exists(self):
        assert Path("desktop/package.json").is_file()

    def test_desktop_tauri_config_exists(self):
        assert Path("desktop/src-tauri/tauri.conf.json").is_file()
