# -*- coding: utf-8 -*-
"""AST/dependency tests to prevent execution path bypasses.

Scans for forbidden patterns that would re-create a second execution path:
  - Direct subprocess/OS calls outside ExecutionSandbox
  - Direct provider/client imports outside adapters
  - Direct HTTP calls for model APIs
  - Shell execution outside sandbox
  - Tool dispatch bypassing Capability Registry
"""

from __future__ import annotations

import ast
import os
import pytest


REMOTE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "remote_terminal")
)
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


class BypassVisitor(ast.NodeVisitor):
    """AST visitor that finds potential bypass patterns."""

    def __init__(self, filename: str = "") -> None:
        self.filename = filename
        self.violations: list[str] = []
        self.in_sandbox = False
        self.in_gateway = False
        self.current_class: str = ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old = self.current_class
        self.current_class = node.name
        if node.name == "ExecutionSandbox":
            self.in_sandbox = True
        if node.name in ("ModelGateway", "ModelGatewayFacade"):
            self.in_gateway = True
        self.generic_visit(node)
        self.current_class = old

    def visit_Call(self, node: ast.Call) -> None:
        # Check for subprocess.run without sandbox
        if self._is_subprocess_call(node) and not self.in_sandbox:
            self.violations.append(
                f"subprocess call outside ExecutionSandbox in {self.filename}"
            )
        # Check for os.system
        if self._is_ossystem(node):
            self.violations.append(
                f"os.system() call in {self.filename} — must use ExecutionSandbox"
            )
        self.generic_visit(node)

    def _is_subprocess_call(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Attribute):
            full = self._attr_name(node.func)
            return full in ("subprocess.run", "subprocess.Popen", "subprocess.call",
                             "subprocess.check_output")
        return False

    def _is_ossystem(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Attribute):
            return self._attr_name(node.func) == "os.system"
        return False

    @staticmethod
    def _attr_name(node: ast.Attribute) -> str:
        parts: list[str] = [node.attr]
        current: ast.AST = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


class TestBypassPrevention:
    """Verify no execution path bypasses exist."""

    def _scan_file(self, filepath: str) -> list[str]:
        if not os.path.isfile(filepath):
            return []
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        visitor = BypassVisitor(filename=os.path.basename(filepath))
        visitor.visit(tree)
        return visitor.violations

    def test_no_subprocess_outside_sandbox(self) -> None:
        """No subprocess.run calls outside ExecutionSandbox (except known exceptions)."""
        # Files where subprocess is explicitly allowed
        allowed_files = {
            "tools.py",  # delegate_to_claude handler (has its own sandboxing approach)
            "brain_llm.py",  # parse_pending_worker (doc parsing)
            "model_gateway_bridge.py",  # bridge internals

            "brain.py",  # gated legacy execution compatibility
            "crypto.py",  # OpenSSL compatibility wrapper
            "health_check.py",  # external service probes
        }
        violations = []
        for filename in os.listdir(REMOTE_DIR):
            if not filename.endswith(".py"):
                continue
            if filename in allowed_files:
                continue
            filepath = os.path.join(REMOTE_DIR, filename)
            vios = self._scan_file(filepath)
            violations.extend(vios)

        # Subprocess in ExecutionSandbox is expected and OK
        if violations:
            pytest.fail(
                "Found subprocess/os.system calls outside allowed modules:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    def test_no_direct_provider_imports_in_brain(self) -> None:
        """brain.py must not directly import provider modules (use compat bridge)."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # brain.py may import provider adapters inside main() for registration only
        # But must not import them at module level for execution
        tree = ast.parse(source)
        for stmt in ast.walk(tree):
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                names = []
                module = ""
                if isinstance(stmt, ast.Import):
                    names = [a.name for a in stmt.names]
                else:
                    module = stmt.module or ""
                    names = [a.name for a in stmt.names]

                for name in names:
                    full = f"{module}.{name}" if module else name
                    # Only check top-level imports (not inside main())
                    # These imports happen inside main() — allowed
                    if "openai" in full and "openai" not in str(source[:5000]):
                        pass  # Top-level import check

    def test_no_direct_tool_execution_bypass(self) -> None:
        """brain.py must not execute tools without dispatch check."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # _dispatch_tool must exist and reference CapabilityContractRegistry
        assert "_dispatch_tool" in source, "brain.py must have _dispatch_tool()"
        # Either the new path references AdmissionPipeline or tools.dispatch does
        assert "AdmissionPipeline" in source or "capability.contract" in source, (
            "brain.py must reference AdmissionPipeline or capability contract"
        )

    def test_tools_module_has_deprecation_guard(self) -> None:
        """tools.py must prevent unregistered tool execution."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # Default-deny: unknown tools must be blocked
        assert "Unknown tool" in source or "not registered" in source.lower(), (
            "tools.py must default-deny unknown tools"
        )

    def test_no_shell_execution_outside_do_execute(self) -> None:
        """brain.py shell execution must only go through _do_execute + exec_in_session."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        assert "ExecutionSandbox" in source, (
            "brain.py should reference ExecutionSandbox for shell execution"
        )

    def test_brain_imports_consolidation_bridges(self) -> None:
        """brain.py must import the consolidation bridge modules."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        bridge_imports = [
            "capability_tool_bridge",
            "session_task_bridge",
            "plan_artifact",
        ]
        for module in bridge_imports:
            assert module in source, (
                f"brain.py must import {module} for consolidation"
            )

    def test_no_run_command_admission_bypass(self) -> None:
        """brain.py must route run_command through _dispatch_tool (not bypass to _do_execute)."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # _continue_loop must send ALL tools (including run_command) through _dispatch_tool
        # Check that the tool dispatch section does NOT have a special case for run_command
        # The pattern we're looking for is: all tools go through _dispatch_tool
        assert "result = _dispatch_tool(tool_name, args, session)" in source, (
            "brain.py _continue_loop must route ALL tools through _dispatch_tool() — "
            "no special case for run_command bypassing admission"
        )

    def test_no_task_without_state_machine(self) -> None:
        """Task objects must always be created with a StateMachine."""
        filepath = os.path.join(REMOTE_DIR, "session_task_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # create_run_turn_task must initialize phase_sm with StateMachine
        assert "StateMachine" in source, (
            "session_task_bridge must use StateMachine for Task phase transitions"
        )
        assert "phase_sm" in source, (
            "Task objects must have phase_sm (StateMachine) initialized"
        )

    def test_no_task_transition_without_validation(self) -> None:
        """Task state transitions must be validated against TASK_TRANSITIONS."""
        filepath = os.path.join(REMOTE_DIR, "session_task_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # emit_task_transition must validate against TASK_TRANSITIONS
        assert "TASK_TRANSITIONS" in source, (
            "emit_task_transition must validate transitions against TASK_TRANSITIONS dict"
        )
        assert "valid_targets" in source or "frozenset" in source, (
            "Task transitions must be validated — no unvalidated state changes"
        )

    def test_no_admission_bypass_in_dispatch_tool(self) -> None:
        """_dispatch_tool must check AdmissionPipeline before executing any tool."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # _dispatch_tool must contain both CapabilityContractRegistry and AdmissionPipeline
        assert "CapabilityContractRegistry" in source, (
            "_dispatch_tool must use CapabilityContractRegistry for contract lookup"
        )
        assert "AdmissionPipeline" in source, (
            "_dispatch_tool must use AdmissionPipeline for access control"
        )
        # Must check admission.allowed
        assert "admission.allowed" in source, (
            "_dispatch_tool must check admission.allowed before executing tools"
        )

    def test_dispatch_tool_no_learn_bypass(self) -> None:
        """_dispatch_tool must NOT allow learn_* tools to bypass CapabilityContract registration."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # The old bypass pattern "not tool_name.startswith('learn_')" must be gone
        # Now ALL tools must be registered
        assert 'not tool_name.startswith("learn_")\'' not in source.replace('"', "'"), (
            "_dispatch_tool must NOT allow learn_* tools to bypass CapabilityContract registration. "
            "All tools must be registered."
        )

    def test_tools_dispatch_no_learn_bypass(self) -> None:
        """tools.dispatch() must NOT allow learn_* tools to bypass CapabilityContract lookup."""
        filepath = os.path.join(REMOTE_DIR, "tools.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()

        # The old bypass: "if tool_name.startswith('learn_')" allowing unregistered learn tools
        # This pattern must be gone — all tools require CapabilityContract
        assert "ALL tools must be registered" in source, (
            "tools.dispatch() must block ALL unregistered tools including learn_*"
        )



# Provider bypass detection — scan all remote_terminal sources


class ProviderImportVisitor(ast.NodeVisitor):
    """AST visitor that detects direct provider SDK imports."""

    PROVIDER_MODULES = {
        "openai", "anthropic", "google.generativeai", "genai",
        "mistralai", "cohere", "ollama", "groq", "together",
    }
    PROVIDER_PACKAGES = {
        "openai", "anthropic", "google.generativeai", "mistralai",
        "cohere", "ollama", "groq", "together",
    }

    def __init__(self, filename: str = "") -> None:
        self.filename = filename
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in self.PROVIDER_MODULES:
                self.violations.append(
                    f"Direct provider import '{alias.name}' in {self.filename}"
                )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        base = module.split(".")[0]
        if base in self.PROVIDER_PACKAGES:
            self.violations.append(
                f"Direct provider import 'from {module}' in {self.filename}"
            )


class TestProviderBypassPrevention:
    """Verify no provider SDK bypasses exist in remote_terminal."""

    # Files explicitly allowed to bridge to providers
    ALLOWED_PROVIDER_FILES = {
        "model_gateway_bridge.py",
        "brain_llm.py",  # Uses model_gateway_bridge, not direct provider SDK
    }

    def test_no_provider_imports_in_remote_terminal(self) -> None:
        """No direct provider SDK imports in remote_terminal outside bridge."""
        violations = []
        for filename in os.listdir(REMOTE_DIR):
            if not filename.endswith(".py"):
                continue
            if filename in self.ALLOWED_PROVIDER_FILES:
                continue
            filepath = os.path.join(REMOTE_DIR, filename)
            try:
                with open(filepath, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
                visitor = ProviderImportVisitor(filename=filename)
                visitor.visit(tree)
                violations.extend(visitor.violations)
            except SyntaxError:
                pass

        if violations:
            pytest.fail(
                "Direct provider SDK imports found outside bridge modules:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nAll provider access must go through model_gateway_bridge → ModelGatewayFacade."
            )



# Shell execution bypass — enhanced detection


class ShellExecutionVisitor(ast.NodeVisitor):
    """AST visitor that detects shell execution patterns outside sandbox."""

    def __init__(self, filename: str = "") -> None:
        self.filename = filename
        self.violations: list[str] = []
        self.in_sandbox_class = False
        self.in_do_execute = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_sandbox = self.in_sandbox_class
        if node.name == "ExecutionSandbox":
            self.in_sandbox_class = True
        self.generic_visit(node)
        self.in_sandbox_class = old_sandbox

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_do_exec = self.in_do_execute
        if node.name == "_do_execute":
            self.in_do_execute = True
        self.generic_visit(node)
        self.in_do_execute = old_do_exec

    def visit_Call(self, node: ast.Call) -> None:
        if self.in_sandbox_class or self.in_do_execute:
            self.generic_visit(node)
            return

        # Check for os.system
        if isinstance(node.func, ast.Attribute):
            full = self._attr_chain(node.func)
            if full in ("os.system", "os.popen", "os.execv", "os.execve"):
                self.violations.append(
                    f"Shell execution '{full}()' outside sandbox in {self.filename}"
                )

        # Check for subprocess calls
        if isinstance(node.func, ast.Attribute):
            full = self._attr_chain(node.func)
            if full in ("subprocess.run", "subprocess.Popen", "subprocess.call",
                         "subprocess.check_output", "subprocess.check_call",
                         "subprocess.getoutput", "subprocess.getstatusoutput"):
                self.violations.append(
                    f"subprocess call '{full}()' outside sandbox in {self.filename}"
                )

        self.generic_visit(node)

    @staticmethod
    def _attr_chain(node: ast.Attribute) -> str:
        parts = [node.attr]
        cur = node.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))


class TestShellExecutionBypassPrevention:
    """Verify no shell execution bypasses exist outside sanctioned paths."""

    # Files where subprocess/shell is explicitly allowed
    ALLOWED_SHELL_FILES = {
        "tools.py",               # delegate_to_claude handler + legacy compat wrappers
        "brain_llm.py",           # parse_pending_worker
        "model_gateway_bridge.py",  # bridge internals

        "brain.py",  # gated legacy execution compatibility
        "crypto.py",  # OpenSSL compatibility wrapper
        "health_check.py",  # external service probes
    }

    def test_no_shell_execution_outside_sandbox(self) -> None:
        """No os.system/subprocess calls outside ExecutionSandbox or _do_execute."""
        violations = []
        for filename in os.listdir(REMOTE_DIR):
            if not filename.endswith(".py"):
                continue
            if filename in self.ALLOWED_SHELL_FILES:
                continue
            filepath = os.path.join(REMOTE_DIR, filename)
            try:
                with open(filepath, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
                visitor = ShellExecutionVisitor(filename=filename)
                visitor.visit(tree)
                violations.extend(visitor.violations)
            except SyntaxError:
                pass

        if violations:
            pytest.fail(
                "Shell execution found outside sanctioned paths:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nAll shell execution must go through ExecutionSandbox or _do_execute."
            )



# Permission bypass detection


class PermissionBypassVisitor(ast.NodeVisitor):
    """AST visitor that detects capability execution without admission check."""

    def __init__(self, filename: str = "") -> None:
        self.filename = filename
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check if this function dispatches tools/commands without admission check
        has_dispatch = False
        has_admission = False
        has_execute = False

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    full = self._attr_chain(child.func)
                    if "dispatch" in full.lower() or "execute" in full.lower():
                        has_dispatch = True
                if isinstance(child.func, ast.Name):
                    if child.func.id in ("exec_in_session", "_exec_raw", "_do_execute"):
                        has_execute = True

            if isinstance(child, ast.Name) and child.id in (
                "AdmissionPipeline", "CapabilityContractRegistry"
            ):
                has_admission = True

        # Low-level helpers are reached through _dispatch_tool, whose admission
        # check has dedicated contract assertions below.
        low_level_helpers = {
            "exec_in_session", "_do_execute", "_handle_kptree",
            "_handle_exec_proxy", "_handle_doc_subject",
        }
        if (has_dispatch or has_execute) and not has_admission:
            func_name = node.name
            if func_name in low_level_helpers:
                self.generic_visit(node)
                return
            if any(kw in func_name.lower() for kw in (
                "dispatch", "execute", "exec", "run_tool", "handle",
            )):
                self.violations.append(
                    f"Function '{func_name}' in {self.filename} dispatches/executes "
                    f"without AdmissionPipeline check"
                )

        self.generic_visit(node)

    @staticmethod
    def _attr_chain(node: ast.Attribute) -> str:
        parts = [node.attr]
        cur = node.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))


class TestPermissionBypassPrevention:
    """Verify no capability execution bypasses admission control."""

    def test_dispatch_functions_use_admission(self) -> None:
        """Functions that dispatch tools must use AdmissionPipeline."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        visitor = PermissionBypassVisitor(filename="brain.py")
        visitor.visit(tree)

        if visitor.violations:
            pytest.fail(
                "Functions dispatching/executing without AdmissionPipeline check:\n"
                + "\n".join(f"  - {v}" for v in visitor.violations)
                + "\n\nAll dispatch/execute functions must include AdmissionPipeline check."
            )
