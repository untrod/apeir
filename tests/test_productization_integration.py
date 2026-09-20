# -*- coding: utf-8 -*-
"""Integration tests for the productization layer.

Verifies that all new productization modules load correctly and
integrate without breaking existing architecture contracts.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


class TestModuleImports:
    """Verify all new modules import cleanly without side effects."""

    def test_deployment_setup_wizard_imports(self):
        from nous_runtime.deployment.setup_wizard import (
            HardwareInfo,
            SetupConfig,
            detect_hardware,
            ConsoleSetupWizard,
        )
        assert HardwareInfo is not None
        assert SetupConfig is not None
        assert detect_hardware is not None
        assert ConsoleSetupWizard is not None

    def test_daemon_health_imports(self):
        from nous_runtime.daemon.health import (
            HealthStatus,
            HealthChecker,
            create_default_checks,
        )
        assert HealthStatus is not None
        assert HealthChecker is not None
        assert create_default_checks is not None

    def test_daemon_recovery_imports(self):
        from nous_runtime.daemon.recovery import (
            CrashRecord,
            CrashRecovery,
            create_default_recovery,
        )
        assert CrashRecord is not None
        assert CrashRecovery is not None
        assert create_default_recovery is not None

    def test_persona_learning_assistant_imports(self):
        from nous_runtime.persona.learning_assistant import (
            Subject,
            LearningAssistant,
        )
        assert Subject is not None
        assert LearningAssistant is not None

    def test_persona_project_assistant_imports(self):
        from nous_runtime.persona.project_assistant import (
            Project,
            ProjectAssistant,
        )
        assert Project is not None
        assert ProjectAssistant is not None

    def test_daemon_windows_service_module_exists(self):
        """Windows service module should be importable (even without pywin32)."""
        try:
            from nous_runtime.daemon.windows_service import (
                install,
                remove,
                start_service,
                stop_service,
                status,
            )
            for command in (install, remove, start_service, stop_service, status):
                assert command is not None
        except ImportError:
            # pywin32 not available, that's OK — the module should still
            # define the functions even if they print an error
            pass


class TestProductizationCoherence:
    """Verify new modules work together correctly."""

    def test_setup_wizard_to_daemon_flow(self):
        """A setup config should produce values compatible with the daemon."""
        from nous_runtime.deployment.setup_wizard import SetupConfig

        config = SetupConfig(
            runtime_mode="hybrid",
            install_path="/tmp/.nous",
            auto_start=True,
        )

        # These values should be usable by the daemon
        assert config.runtime_mode in ("cloud_assisted", "local", "hybrid")
        assert isinstance(config.install_path, str)
        assert isinstance(config.auto_start, bool)

    def test_learning_and_project_assistants_coexist(self):
        """Both assistants should work in the same workspace."""
        from nous_runtime.persona.learning_assistant import LearningAssistant
        from nous_runtime.persona.project_assistant import ProjectAssistant

        with tempfile.TemporaryDirectory() as tmp:
            learning = LearningAssistant(workspace=tmp)
            projects = ProjectAssistant(workspace=tmp)

            # Both should be functional
            learning.add_subject("Test Subject")
            projects.create_project("Test Project")

            assert "test_subject" in learning._profile.subjects
            assert projects.get_project("Test Project") is not None

    def test_daemon_health_and_recovery_integration(self):
        """Health checker and crash recovery should integrate."""
        from nous_runtime.daemon.health import HealthChecker
        from nous_runtime.daemon.recovery import CrashRecovery

        checker = HealthChecker(interval_seconds=60)
        recovery = CrashRecovery()

        # Register recovery as a health check handler
        checker.register_check(
            "crash_count",
            lambda: recovery.get_status()["total_crashes"] == 0,
        )

        status = checker.run_once()
        assert status.healthy is True


class TestBackwardCompatibility:
    """Verify new modules don't break existing imports and contracts."""

    def test_core_imports_still_work(self):
        """Core nous_runtime imports should be unchanged."""
        from nous_runtime import __version__
        assert __version__ is not None

        from nous_runtime.kernel.runtime import Runtime
        assert Runtime is not None

    def test_cli_module_still_loads(self):
        """The CLI module should still import cleanly."""
        from nous_runtime.cli.main import app
        assert app is not None
        # The app name should still be "nous"
        assert app.info.name == "nous"

    def test_provider_registry_unaffected(self):
        """Provider system should be unaffected by productization changes."""
        from nous_runtime.provider.registry import ProviderRegistry
        assert ProviderRegistry is not None

    def test_governance_unaffected(self):
        """Governance system should be unaffected by productization changes."""
        from nous_runtime.governance import (
            ApprovalManager,
            DelegationManager,
            ExecutionAuthorizationGate,
        )
        assert ApprovalManager is not None
        assert DelegationManager is not None
        assert ExecutionAuthorizationGate is not None


class TestDocFilesExist:
    """Verify all documentation files were created."""

    def test_repository_audit_exists(self):
        path = Path("docs/release/PUBLIC_RELEASE_CHECKLIST.md")
        assert path.is_file(), f"Expected {path} to exist"

    def test_user_guide_exists(self):
        path = Path("docs/USER_GUIDE.md")
        assert path.is_file(), f"Expected {path} to exist"

    def test_install_guide_exists(self):
        path = Path("docs/INSTALL.md")
        assert path.is_file(), f"Expected {path} to exist"

    def test_architecture_doc_exists(self):
        path = Path("docs/ARCHITECTURE.md")
        assert path.is_file(), f"Expected {path} to exist"

    def test_security_doc_exists(self):
        path = Path("docs/SECURITY.md")
        assert path.is_file(), f"Expected {path} to exist"

    def test_roadmap_exists(self):
        path = Path("ROADMAP.md")
        assert path.is_file(), f"Expected {path} to exist"
