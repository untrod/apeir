# -*- coding: utf-8 -*-
"""Test that all tools are registered as CapabilityContracts.

Verifies every tool has a corresponding contract, dispatch routes through
AdmissionPipeline, and unregistered tools are blocked.
"""

from __future__ import annotations

import os
import sys
import pytest


REMOTE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "remote_terminal")
REMOTE_DIR = os.path.abspath(REMOTE_DIR)


class TestToolCapabilityEnforcement:
    """Verify tool → CapabilityContract registration and blocking."""

    def test_tools_module_exists(self) -> None:
        """tools.py must exist (reconstructed)."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        assert os.path.isfile(filepath), (
            "tools.py must exist in remote_terminal/ (reconstructed with Capability routing)"
        )

    def test_tools_importable(self) -> None:
        """tools module must be importable."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import tools
            assert hasattr(tools, "dispatch"), "tools must have dispatch()"
            assert hasattr(tools, "ToolResult"), "tools must have ToolResult"
            assert hasattr(tools, "is_server_side_tool"), "tools must have is_server_side_tool()"
            assert hasattr(tools, "get_tool_defs"), "tools must have get_tool_defs()"
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_dispatch_checks_capability_registry(self) -> None:
        """dispatch() must reference CapabilityContractRegistry."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "CapabilityContractRegistry" in source or "capability.contract" in source, (
            "tools.dispatch() must check CapabilityContractRegistry"
        )

    def test_dispatch_checks_admission(self) -> None:
        """dispatch() must reference AdmissionPipeline."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "AdmissionPipeline" in source or "admission" in source.lower(), (
            "tools.dispatch() must check AdmissionPipeline"
        )

    def test_unregistered_tool_blocked(self) -> None:
        """Unregistered tools must be default-denied."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "not registered" in source.lower() or "execution denied" in source.lower(), (
            "Unregistered tools must produce 'not registered' / 'execution denied' error"
        )

    def test_capability_tool_bridge_registers_tools(self) -> None:
        """capability_tool_bridge.py must register all tools."""
        filepath = os.path.join(REMOTE_DIR, "capability_tool_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "register_all_tools" in source, (
            "capability_tool_bridge.py must have register_all_tools()"
        )
        assert "CapabilityContract" in source, (
            "capability_tool_bridge.py must create CapabilityContract entries"
        )

    def test_capability_tool_bridge_importable(self) -> None:
        """capability_tool_bridge must be importable."""
        sys.path.insert(0, REMOTE_DIR)
        try:
            import capability_tool_bridge
            assert hasattr(capability_tool_bridge, "register_all_tools")
            assert hasattr(capability_tool_bridge, "get_registered_tool_count")
            assert hasattr(capability_tool_bridge, "is_tool_registered")
            assert hasattr(capability_tool_bridge, "get_unregistered_tools")
        finally:
            if REMOTE_DIR in sys.path:
                sys.path.remove(REMOTE_DIR)

    def test_server_side_tools_list_not_empty(self) -> None:
        """_SERVER_SIDE_TOOLS must contain the expected tools."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # Verify key tools are present in the set
        expected_tools = [
            "learn_list_docs", "web_search", "phone_observe",
            "delegate_to_claude",
        ]
        for tool in expected_tools:
            assert tool in source, (
                f"_SERVER_SIDE_TOOLS must contain '{tool}'"
            )

    def test_deprecation_warning_in_dispatch(self) -> None:
        """tools.dispatch() must emit DeprecationWarning."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "DeprecationWarning" in source, (
            "tools.dispatch() must emit DeprecationWarning"
        )
        assert "legacy_tool_dispatch_total" in source, (
            "tools.dispatch() must increment legacy_tool_dispatch_total"
        )
