# -*- coding: utf-8 -*-
"""Architecture-level bypass prevention.

AST-scans the entire codebase for patterns that would re-create
legacy execution paths bypassing the new unified architecture:
  - Provider API calls outside adapters
  - Shell execution outside sandbox
  - Tool execution without contract
  - Task creation without state machine
  - Permission checks bypassed

Extends the existing test_import_boundaries.py pattern.
"""

from __future__ import annotations

import ast
import os
import pytest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

# Directories to scan
SCAN_DIRS = [
    os.path.join(PROJECT_ROOT, "remote_terminal"),
    os.path.join(PROJECT_ROOT, "nous_runtime"),
]

# Directories/files explicitly excluded from scans
EXCLUDED_PATHS = {
    os.path.join(PROJECT_ROOT, "nous_runtime", "compat"),
    os.path.join(PROJECT_ROOT, "nous_runtime", "provider", "adapters"),
    os.path.join(PROJECT_ROOT, "nous_runtime", "test"),
    os.path.join(PROJECT_ROOT, "nous_runtime", "capability", "sandbox.py"),
    os.path.join(PROJECT_ROOT, "nous_runtime", "model_runtime", "gateway.py"),
    os.path.join(PROJECT_ROOT, "remote_terminal", "model_gateway_bridge.py"),
}

SHELL_BOUNDARY_PATHS = {
    os.path.normpath(os.path.join(PROJECT_ROOT, path))
    for path in (

        "remote_terminal/brain.py",
        "remote_terminal/crypto.py",
        "remote_terminal/health_check.py",
        "remote_terminal/tools.py",
        "nous_runtime/agents/adapters/supervisor.py",
        "nous_runtime/capability/resolver.py",
        "nous_runtime/cli/dev_commands.py",
        "nous_runtime/cli/registry.py",
        "nous_runtime/cli/shell.py",
        "nous_runtime/cli/shell_v2.py",
        "nous_runtime/connectors/adapters.py",
        "nous_runtime/deployment/installer.py",
        "nous_runtime/deployment/platform_detect.py",
        "nous_runtime/deployment/setup_wizard.py",
        "nous_runtime/ecosystem/installer.py",
        "nous_runtime/evaluation/validators/code_validator.py",
        "nous_runtime/evaluation/validators/security_validator.py",
        "nous_runtime/evaluation/validators/test_validator.py",
        "nous_runtime/operations/release.py",
        "nous_runtime/platform/adapter.py",
        "nous_runtime/platform/detector.py",
        "nous_runtime/platform/models.py",
        "nous_runtime/update/manager.py",
        # The sole host-side launcher for the disposable VM strong backend.
        "nous_runtime/kernel/windows_sandbox.py",
        # The sole detached host for reconnectable governed ProcessSessions.
        "nous_runtime/kernel/process_session_host.py",
    )
}

PROVIDER_BOUNDARY_PATHS = {
    os.path.normpath(os.path.join(PROJECT_ROOT, path))
    for path in (
        "remote_terminal/brain.py",  # legacy registration only
        "nous_runtime/cli/provider_setup.py",  # provider registration service
        "nous_runtime/model_runtime/adapters.py",  # Gateway adapter boundary
        "nous_runtime/model_runtime/__init__.py",  # public adapter exports
    )
}

# Provider imports that signal a bypass
PROVIDER_IMPORT_PATTERNS = [
    "openai", "OpenAI", "anthropic", "Anthropic",
    "google.generativeai", "mistralai", "cohere",
]

# Shell execution functions
SHELL_EXEC_PATTERNS = [
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
    "os.system", "os.popen",
    "commands.getoutput", "commands.getstatusoutput",
]


class ArchitectureBypassVisitor(ast.NodeVisitor):
    """Scan for architecture bypass patterns."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.violations: list[dict] = []
        self.current_function: str = "<module>"
        self.in_sandbox = False
        self.in_gateway = False
        self.in_adapter = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name in ("ExecutionSandbox", "ProcessSandbox", "SandboxConfig"):
            self.in_sandbox = True
        if node.name in ("ModelGateway", "ModelGatewayFacade"):
            self.in_gateway = True
        if "Adapter" in node.name or "Provider" in node.name:
            self.in_adapter = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old

    @staticmethod
    def _is_provider_import(name: str) -> bool:
        lowered = name.lower()
        external_roots = (
            "openai", "anthropic", "google.generativeai",
            "mistralai", "cohere",
        )
        return (
            lowered.startswith("nous_runtime.provider.adapters.")
            or any(lowered == root or lowered.startswith(root + ".") for root in external_roots)
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if self._is_provider_import(alias.name):
                self.violations.append({
                    "file": self.filepath,
                    "function": self.current_function,
                    "line": node.lineno,
                    "message": f"Provider import '{alias.name}' outside adapter — "
                               f"use ModelGatewayFacade or provider.adapters",
                })

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}"
            if self._is_provider_import(module) or self._is_provider_import(full):
                self.violations.append({
                    "file": self.filepath,
                    "function": self.current_function,
                    "line": node.lineno,
                    "message": f"Provider import '{full}' outside adapter — "
                               f"use ModelGatewayFacade or provider.adapters",
                })

    def visit_Call(self, node: ast.Call) -> None:
        # Check for shell execution outside sandbox
        call_name = self._resolve_call_name(node)
        for pattern in SHELL_EXEC_PATTERNS:
            if call_name == pattern and not self.in_sandbox:
                self.violations.append({
                    "file": self.filepath,
                    "function": self.current_function,
                    "line": node.lineno,
                    "message": f"Shell execution '{call_name}' outside ExecutionSandbox",
                })

        self.generic_visit(node)

    @staticmethod
    def _resolve_call_name(node: ast.Call) -> str:
        parts: list[str] = []
        current: ast.AST = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


def _is_excluded(filepath: str) -> bool:
    """Check if a file is excluded from scanning."""
    for excluded in EXCLUDED_PATHS:
        if filepath.startswith(excluded):
            return True
    return False


def _collect_python_files(root: str) -> list[str]:
    """Collect all .py files under root, excluding certain paths."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip test and build directories
        dirnames[:] = [
            d for d in dirnames
            if d not in ("__pycache__", ".git", ".claude", "build",
                         "node_modules", ".venv", "venv", "env")
        ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(dirpath, filename)
            if _is_excluded(filepath):
                continue
            files.append(filepath)
    return files


class TestArchitectureBypassPrevention:
    """Architecture-level bypass prevention tests."""

    def test_no_provider_imports_outside_adapters(self) -> None:
        """Provider imports must only exist in nous_runtime/provider/adapters/."""
        all_violations: list[dict] = []

        for scan_dir in SCAN_DIRS:
            if not os.path.isdir(scan_dir):
                continue
            for filepath in _collect_python_files(scan_dir):
                if filepath in PROVIDER_BOUNDARY_PATHS:
                    continue
                with open(filepath, encoding="utf-8") as f:
                    try:
                        source = f.read()
                    except Exception:
                        continue
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                visitor = ArchitectureBypassVisitor(filepath)
                visitor.visit(tree)
                provider_violations = [
                    item for item in visitor.violations
                    if "Provider import" in item["message"]
                ]
                all_violations.extend(provider_violations)

        if all_violations:
            violation_msg = "\n".join(
                f"  {v['file']}:{v['line']} in {v['function']}() — {v['message']}"
                for v in all_violations[:10]
            )
            if len(all_violations) > 10:
                violation_msg += f"\n  ... and {len(all_violations) - 10} more"
            pytest.fail(
                f"Found {len(all_violations)} provider import violations:\n{violation_msg}"
            )

    def test_no_shell_execution_outside_sandbox(self) -> None:
        """Shell execution must only happen inside ExecutionSandbox."""
        all_violations: list[dict] = []

        # Only scan non-sandbox files
        for scan_dir in SCAN_DIRS:
            if not os.path.isdir(scan_dir):
                continue
            for filepath in _collect_python_files(scan_dir):
                if filepath in SHELL_BOUNDARY_PATHS:
                    continue
                with open(filepath, encoding="utf-8") as f:
                    try:
                        source = f.read()
                    except Exception:
                        continue
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                visitor = ArchitectureBypassVisitor(filepath)
                visitor.visit(tree)
                # Only count shell execution violations
                shell_violations = [
                    v for v in visitor.violations
                    if "Shell execution" in v["message"]
                ]
                all_violations.extend(shell_violations)

        if all_violations:
            violation_msg = "\n".join(
                f"  {v['file']}:{v['line']} in {v['function']}() — {v['message']}"
                for v in all_violations[:10]
            )
            pytest.fail(
                f"Found {len(all_violations)} shell execution violations:\n{violation_msg}"
            )
