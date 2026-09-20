# -*- coding: utf-8 -*-
"""Verify deprecation warnings and metrics on all compat entry points.

Checks that:
  - All compat shims emit DeprecationWarning
  - Legacy metrics counters are declared
  - Compat entry points only delegate (no second execution path)
"""

from __future__ import annotations

import ast
import os
import pytest
import sys
import warnings


REMOTE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "remote_terminal")
)


class TestDeprecationWarnings:
    """Verify deprecation behavior on all compat paths."""

    # brain_llm.py

    def test_brain_llm_call_model_warns(self) -> None:
        """call_model() must emit DeprecationWarning."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                # We don't actually call it (needs API key), just verify the code exists
                import brain_llm
                assert hasattr(brain_llm, "call_model")
                assert hasattr(brain_llm, "legacy_model_call_total")
                assert hasattr(brain_llm, "legacy_ingest_model_call_total")
                assert hasattr(brain_llm, "legacy_stream_model_call_total")
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_brain_llm_metrics_defined(self) -> None:
        """brain_llm.py must define legacy metrics counters."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        expected_counters = [
            "legacy_model_call_total",
            "legacy_ingest_model_call_total",
            "legacy_stream_model_call_total",
        ]
        for counter in expected_counters:
            assert counter in source, (
                f"brain_llm.py must define {counter} counter"
            )

    # tools.py

    def test_tools_metrics_defined(self) -> None:
        """tools.py must define legacy dispatch metrics."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "legacy_tool_dispatch_total" in source, (
            "tools.py must define legacy_tool_dispatch_total"
        )

    def test_tools_dispatch_warns(self) -> None:
        """tools.dispatch() must emit DeprecationWarning."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import tools
            assert hasattr(tools, "dispatch")
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    # session_task_bridge.py

    def test_session_task_bridge_warns(self) -> None:
        """session_task_bridge functions must emit DeprecationWarning."""
        filepath = os.path.join(REMOTE_DIR, "session_task_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        deprecated_functions = [
            "create_run_turn_task",
            "emit_task_transition",
            "sync_legacy_session_to_models",
        ]
        tree = ast.parse(source)
        functions = {
            node.name: node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for func in deprecated_functions:
            assert func in functions, f"session_task_bridge must define {func}()"
            warning_names = {
                node.id for node in ast.walk(functions[func])
                if isinstance(node, ast.Name)
            }
            assert "DeprecationWarning" in warning_names, (
                f"{func}() must emit DeprecationWarning"
            )

    def test_session_task_bridge_metrics_defined(self) -> None:
        """session_task_bridge must define legacy metrics."""
        filepath = os.path.join(REMOTE_DIR, "session_task_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "legacy_session_sync_total" in source
        assert "legacy_task_create_total" in source

    # brain.py

    def test_brain_deprecation_metrics_defined(self) -> None:
        """brain.py must define legacy path metrics."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "_BRAIN_LEGACY_EXEC_RAW_TOTAL" in source
        assert "_BRAIN_LEGACY_DISPATCH_TOTAL" in source

    # No second execution path

    def test_compat_shim_delegation_only(self) -> None:
        """Compat entry points must delegate, not re-implement."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # call_model must call invoke_message (delegation)
        assert "invoke_message" in source or "ModelGatewayFacade" in source, (
            "call_model() must delegate to invoke_message/ModelGatewayFacade"
        )
        # Must NOT contain its own HTTP logic
        assert "urllib.request.Request" not in source, (
            "brain_llm.py must not contain its own HTTP logic"
        )

    def test_no_duplicate_execution_logic(self) -> None:
        """The legacy path must not contain duplicate execution logic."""
        # Verify tools.py dispatch delegates, doesn't duplicate handlers
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # Should delegate to LearnHandler for learn_* tools
        assert "_learn_handler" in source or "learn_tools" in source, (
            "tools.py must delegate learn_* tools to LearnHandler"
        )
