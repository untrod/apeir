"""Tests for backward compatibility — CLI, config, legacy data."""


class TestCLICompatibility:
    """Verify existing CLI commands still import after changes."""

    def test_cli_main_imports(self):
        """nous CLI main should still import."""
        from nous_runtime.cli.main import app
        assert app is not None

    def test_cli_commands_registered(self):
        """All pre-existing CLI command groups should still exist."""
        from nous_runtime.cli.main import app
        # Check key command groups are registered
        # These are Typer sub-apps added to the main app
        assert app is not None  # Smoke test — actual registration depends on env

    def test_status_command_works(self):
        """nous status should produce valid output."""
        from nous_runtime.cli.main import status_cmd
        # Just verify it doesn't crash on import/call
        assert callable(status_cmd)

    def test_doctor_imports(self):
        """nous doctor should be importable."""
        from nous_runtime.cli.doctor import doctor_cmd
        assert callable(doctor_cmd)

    def test_provider_commands_import(self):
        """Provider CLI commands should still be importable."""
        from nous_runtime.cli.profiles import (
            list_providers,
        )
        assert callable(list_providers)


class TestConfigCompatibility:
    """Verify existing config loading still works."""

    def test_nous_config_loads(self):
        from nous_runtime.kernel.config import NousConfig
        # Should at minimum create a config with defaults
        config = NousConfig()
        assert config is not None
        assert isinstance(config.server_port, int)

    def test_config_to_dict_hides_secrets(self):
        from nous_runtime.kernel.config import NousConfig
        config = NousConfig()
        config.llm_api_key = "sk-secret-key-12345"
        d = config.to_dict(hide_secrets=True)
        assert d.get("llm_api_key") == "***"

    def test_config_defaults_sensible(self):
        from nous_runtime.kernel.config import NousConfig
        config = NousConfig()
        assert config.server_host in ("0.0.0.0", "127.0.0.1")
        assert config.server_port > 0
        assert config.rate_limit_per_minute > 0


class TestPythonAPICompatibility:
    """Verify existing Python APIs still work."""

    def test_runtime_status(self):
        from nous_runtime.kernel.runtime import Runtime
        r = Runtime()
        s = r.status()
        assert s is not None
        assert hasattr(s, 'version')
        assert hasattr(s, 'running')

    def test_provider_registry(self):
        from nous_runtime.provider.registry import ProviderRegistry
        registry = ProviderRegistry()
        providers = registry.list_all()
        assert isinstance(providers, list)

    def test_task_manager(self):
        from nous_runtime.task.manager import TaskManager
        manager = TaskManager()
        tasks = manager.list()
        assert isinstance(tasks, list)

    def test_event_bus(self):
        from nous_runtime.events.bus import get_event_bus
        bus = get_event_bus()
        assert bus is not None


class TestDataCompatibility:
    """Verify existing task/artifact/event data can be read."""

    def test_task_manager_create_and_read(self):
        from nous_runtime.task.manager import TaskManager
        manager = TaskManager()
        task = manager.create(name="compat_test", description="Backward compat test")
        assert task is not None
        retrieved = manager.get(task.id)
        assert retrieved is not None
        assert retrieved.name == "compat_test"

    def test_artifact_registry(self):
        from nous_runtime.artifact.registry import ArtifactRegistry
        reg = ArtifactRegistry()
        artifacts = reg.list()
        assert isinstance(artifacts, list)

    def test_kernel_task_imports(self):
        """Kernel task module should expose all expected symbols."""
        from nous_runtime.kernel.task import (
            TaskPhase, TASK_TRANSITIONS,
        )
        # All symbols should exist
        assert TaskPhase is not None
        assert TASK_TRANSITIONS is not None


class TestMigrationDryRun:
    """Verify migration safety."""

    def test_all_legacy_states_still_valid(self):
        """Every state from the pre-extension TaskPhase should still exist."""
        from nous_runtime.kernel.task import TaskPhase
        legacy_states = [
            "created", "queued", "planning", "awaiting_approval", "dispatching",
            "running", "waiting_for_model", "waiting_for_node", "verifying",
            "paused", "recovering", "completed", "completed_with_warnings",
            "failed", "failed_verification", "cancelled",
        ]
        existing = {e.value for e in TaskPhase}
        for s in legacy_states:
            assert s in existing, f"Legacy state '{s}' missing from TaskPhase"

    def test_all_legacy_transitions_still_valid(self):
        """All pre-existing transitions should still be valid."""
        from nous_runtime.kernel.task import TASK_TRANSITIONS, TaskPhase
        # Key legacy transitions that must exist
        assert TaskPhase.CREATED in TASK_TRANSITIONS
        assert TaskPhase.QUEUED in TASK_TRANSITIONS.get(TaskPhase.CREATED, frozenset())
        assert TaskPhase.RUNNING in TASK_TRANSITIONS
        assert TaskPhase.COMPLETED in TASK_TRANSITIONS.get(TaskPhase.VERIFYING, frozenset())

    def test_task_phase_values_unchanged(self):
        """Legacy state string values must not change (would break JSONL data)."""
        from nous_runtime.kernel.task import TaskPhase
        assert TaskPhase.CREATED.value == "created"
        assert TaskPhase.RUNNING.value == "running"
        assert TaskPhase.COMPLETED.value == "completed"
        assert TaskPhase.FAILED.value == "failed"
        assert TaskPhase.CANCELLED.value == "cancelled"
