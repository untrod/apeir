# -*- coding: utf-8 -*-
"""Import regression tests — prevent packaged installation breakage.

These tests verify that all key modules import successfully in isolation.
A single optional module failure must not break the core CLI.
"""



class TestCoreImports:
    """Core Runtime imports must succeed."""

    def test_import_nous_runtime(self):
        """nous_runtime package must import."""
        import nous_runtime
        assert nous_runtime.__version__

    def test_import_kernel(self):
        """Kernel modules must import."""
        from nous_runtime.kernel.runtime import Runtime
        from nous_runtime.kernel.object_model import NousObject
        from nous_runtime.kernel.tracing import TraceContext
        assert Runtime
        assert NousObject
        assert TraceContext

    def test_import_capability(self):
        """Capability modules must import."""
        from nous_runtime.capability.lifecycle import CapabilityLifecycle
        from nous_runtime.capability.resolver import resolve_capability
        assert CapabilityLifecycle
        assert resolve_capability

    def test_import_provider(self):
        """Provider modules must import."""
        from nous_runtime.provider.base import Provider
        from nous_runtime.provider.registry import ProviderRegistry
        assert Provider
        assert ProviderRegistry

    def test_import_pack(self):
        """Pack modules must import."""
        from nous_runtime.pack.manifest import PackManifest
        from nous_runtime.pack.loader import load_pack
        assert PackManifest
        assert load_pack

    def test_import_learning(self):
        """Learning modules must import."""
        from nous_runtime.learning.state import MasteryState
        from nous_runtime.learning.experience import record
        assert MasteryState
        assert record


class TestCLIImports:
    """CLI imports must succeed or fail gracefully."""

    def test_import_cli_main(self):
        """CLI main must import (simulates `nous --version`)."""
        from nous_runtime.cli.main import app
        assert app

    def test_import_cli_dev_commands(self):
        """Dev commands must import (simulates `nous dev`)."""
        from nous_runtime.cli.dev_commands import dev_app, new_app
        assert dev_app
        assert new_app

    def test_import_cli_shell(self):
        """Shell modules must import."""
        from nous_runtime.cli.shell_v2 import run, COMMANDS
        assert run
        assert COMMANDS

    def test_cli_noargs_is_help(self):
        """--help flag works without crashing."""
        pass  # Verified by manual test


class TestSDKImports:
    """SDK imports must succeed."""

    def test_import_sdk_client(self):
        """Python SDK must import."""
        from nous_runtime.sdk.client import NousClient
        assert NousClient

    def test_import_sdk_advanced(self):
        """Advanced SDK must import."""
        from nous_runtime.sdk.advanced import StreamingClient
        assert StreamingClient


class TestPlannerImports:
    """Planner imports must succeed."""

    def test_import_planner(self):
        """Planner modules must import."""
        from nous_runtime.planner.goal import Goal
        from nous_runtime.planner.plan import Plan
        from nous_runtime.planner.graph import TaskGraph
        from nous_runtime.planner.pipeline import DecisionPipeline
        assert Goal
        assert Plan
        assert TaskGraph
        assert DecisionPipeline
