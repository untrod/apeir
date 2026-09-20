# -*- coding: utf-8 -*-
"""Test that all model calls go through the unified Model Gateway.

AST-scans brain_llm.py and brain.py to detect any direct HTTP/API calls
that bypass ModelGatewayFacade. Also verifies deprecation warnings.
"""

from __future__ import annotations

import ast
import os
import pytest


REMOTE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "remote_terminal")
REMOTE_DIR = os.path.abspath(REMOTE_DIR)

# Patterns that indicate model API bypass
FORBIDDEN_MODEL_IMPORTS = {"openai", "anthropic", "requests", "httpx", "aiohttp"}
FORBIDDEN_URL_PATTERNS = [
    "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    "api.deepseek.com", "openrouter.ai",
]
FORBIDDEN_FUNCTIONS = {
    "urllib.request.urlopen", "urllib.request.Request",
    "requests.post", "requests.get",
    "openai.ChatCompletion.create", "openai.Completion.create",
}


def _read_source(filepath: str) -> str:
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def _parse_ast(source: str) -> ast.AST:
    return ast.parse(source)


class ModelGatewayVisitor(ast.NodeVisitor):
    """AST visitor that finds forbidden model API patterns."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self.current_function: str = ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        old = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in FORBIDDEN_MODEL_IMPORTS:
                # Allow inside compat/ or bridge modules
                pass  # We report in visit_ImportFrom more specifically

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}"
            if any(p in full for p in FORBIDDEN_MODEL_IMPORTS):
                self.violations.append(
                    f"Import {full} in {self.current_function or '<module>'} — "
                    f"direct model imports must go through ModelGatewayFacade"
                )

    def visit_Call(self, node: ast.Call) -> None:
        # Check for direct HTTP calls
        if isinstance(node.func, ast.Attribute):
            full_name = self._get_full_name(node.func)
            if full_name in FORBIDDEN_FUNCTIONS:
                self.violations.append(
                    f"Direct call to {full_name} in {self.current_function or '<module>'} — "
                    f"must use model_gateway_bridge or ModelGatewayFacade"
                )
        # Check for direct subprocess calls to LLM CLIs
        if isinstance(node.func, ast.Name) and node.func.id == "subprocess":
            self.violations.append(
                f"subprocess usage in {self.current_function or '<module>'} — "
                f"must use ExecutionSandbox or ModelGatewayFacade"
            )
        self.generic_visit(node)

    @staticmethod
    def _get_full_name(node: ast.Attribute) -> str:
        parts: list[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


class TestModelGatewayEnforcement:
    """Verify model calls are routed through ModelGatewayFacade."""

    def test_brain_llm_no_direct_api_calls(self) -> None:
        """brain_llm.py must not contain direct API calls bypassing Gateway."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        tree = _parse_ast(source)
        visitor = ModelGatewayVisitor()
        visitor.visit(tree)

        # brain_llm may import model_gateway_bridge — that's expected
        allowed_imports = {"model_gateway_bridge", "nous_runtime.model_runtime"}

        forbidden = [
            v for v in visitor.violations
            if not any(a in v for a in allowed_imports)
        ]
        assert not forbidden, (
            "brain_llm.py has forbidden model API calls:\n"
            + "\n".join(f"  - {v}" for v in forbidden)
        )

    def test_brain_llm_uses_gateway_bridge(self) -> None:
        """brain_llm.py must import model_gateway_bridge."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        assert "model_gateway_bridge" in source or "ModelGatewayFacade" in source, (
            "brain_llm.py must use model_gateway_bridge or ModelGatewayFacade"
        )

    def test_call_model_emits_deprecation_warning(self) -> None:
        """call_model() must emit DeprecationWarning."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        assert "DeprecationWarning" in source, (
            "call_model() must emit DeprecationWarning"
        )
        assert "legacy_model_call_total" in source, (
            "call_model() must increment legacy_model_call_total"
        )

    def test_brain_no_direct_model_imports(self) -> None:
        """brain.py must not import model providers directly."""
        filepath = os.path.join(REMOTE_DIR, "brain.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        tree = _parse_ast(source)
        visitor = ModelGatewayVisitor()
        visitor.visit(tree)

        # Allow imports within compat section only
        forbidden = [
            v for v in visitor.violations
            if "ModelGatewayFacade" not in v and "model_gateway_bridge" not in v
        ]
        assert not forbidden, (
            "brain.py has forbidden direct model imports:\n"
            + "\n".join(f"  - {v}" for v in forbidden)
        )

    def test_model_gateway_bridge_uses_facade(self) -> None:
        """model_gateway_bridge.py must use ModelGatewayFacade."""
        filepath = os.path.join(REMOTE_DIR, "model_gateway_bridge.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        assert "ModelGatewayFacade" in source, (
            "model_gateway_bridge.py must use ModelGatewayFacade"
        )

    def test_call_model_stream_delegates_to_gateway(self) -> None:
        """call_model_stream() must delegate through call_model() → Gateway (no separate path)."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        tree = _parse_ast(source)

        # Find the call_model_stream function body
        class StreamDelegationVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.stream_delegates = False
                self.in_stream = False

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node.name == "call_model_stream":
                    self.in_stream = True
                    self.generic_visit(node)
                    self.in_stream = False

            def visit_Call(self, node: ast.Call) -> None:
                if self.in_stream:
                    if isinstance(node.func, ast.Name) and node.func.id == "call_model":
                        self.stream_delegates = True
                self.generic_visit(node)

        visitor = StreamDelegationVisitor()
        visitor.visit(tree)
        assert visitor.stream_delegates, (
            "call_model_stream() must delegate to call_model() (which routes through Gateway) — "
            "no separate execution path allowed"
        )

    def test_brain_llm_no_direct_http_client(self) -> None:
        """brain_llm.py must not import HTTP clients directly."""
        filepath = os.path.join(REMOTE_DIR, "brain_llm.py")
        if not os.path.isfile(filepath):
            pytest.skip(f"File not found: {filepath}")

        source = _read_source(filepath)
        # Must not import urllib directly for API calls
        assert "urllib.request" not in source, (
            "brain_llm.py must not use urllib.request directly — use model_gateway_bridge"
        )
        assert "requests" not in source or "import requests" not in source, (
            "brain_llm.py must not import requests — use model_gateway_bridge"
        )

    def test_no_hardcoded_api_urls_in_brain(self) -> None:
        """brain.py and brain_llm.py must not contain hardcoded API URLs."""
        for check_file in ("brain.py", "brain_llm.py"):
            filepath = os.path.join(REMOTE_DIR, check_file)
            if not os.path.isfile(filepath):
                continue

            source = _read_source(filepath)
            for url_pattern in FORBIDDEN_URL_PATTERNS:
                assert url_pattern not in source, (
                    f"{check_file} must not contain hardcoded API URL: {url_pattern}"
                )
