# -*- coding: utf-8 -*-
"""Pytest fixtures for Nous Runtime tests."""

import os
import sys
import tempfile

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolate_apeir_state(tmp_path, monkeypatch):
    """Keep durable Runtime state isolated between tests."""
    monkeypatch.setenv("APEIR_STATE_DIR", str(tmp_path / "apeir-state"))


@pytest.fixture
def tmp_pack_dir():
    """Create a temporary pack directory with a valid pack.yaml."""
    with tempfile.TemporaryDirectory() as d:
        # Write a minimal pack.yaml
        yaml_path = os.path.join(d, "pack.yaml")
        with open(yaml_path, "w") as f:
            f.write("""name: test_pack
version: 1.0.0
description: Test pack for unit tests

capabilities:
  - test.hello

providers:
  - TestProvider

dependencies:
  runtime: ">=1.0"
""")
        # Write src/__init__.py
        src_dir = os.path.join(d, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, "__init__.py"), "w") as f:
            f.write("""
def register(pack):
    from remote_terminal.nous_core.provider import register_adapter
    from .providers import TestProvider
    register_adapter(TestProvider())
    pack.registered_providers.append("TestProvider")
""")
        with open(os.path.join(src_dir, "providers.py"), "w") as f:
            f.write("""
from remote_terminal.nous_core.provider import Provider

class TestProvider(Provider):
    name = "test_provider"
    version = "1.0.0"

    def list_capabilities(self):
        return ["test.hello"]

    def invoke(self, capability_id, **params):
        return {"ok": True, "message": "hello from test"}

    def health(self):
        return {"status": "ok"}
""")
        yield d


@pytest.fixture
def mock_provider():
    """A simple mock provider for testing."""
    from remote_terminal.nous_core.provider import Provider

    class MockProvider(Provider):
        provider_id = "mock_test"
        name = "mock"
        version = "1.0.0"

        def list_capabilities(self):
            return ["mock.test", "mock.echo"]

        def invoke(self, capability_id, **params):
            return {"ok": True, "capability": capability_id, "params": params}

        def health(self):
            return {"status": "ok"}

    return MockProvider()
_TEST_TIER_BY_PREFIX = {
    "context": "integration",
    "evaluation": "integration",
    "experience": "integration",
    "governance": "security",
    "network": "integration",
    "test_architecture": "runtime",
    "test_capability": "unit",
    "test_cli": "runtime",
    "test_connectivity": "integration",
    "test_integration": "integration",
    "test_kernel": "unit",
    "test_learning": "unit",
    "test_pack": "unit",
    "test_planner": "unit",
    "test_provider": "unit",
}

_RUNTIME_TEST_FILES = {
    "test_agent_runtime.py",
    "test_phase8_runtime_closure.py",
    "test_terminal_shell.py",
}

_SECURITY_TEST_FILES = {
    "test_open_source_hygiene.py",
}


def _tier_for_test_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    try:
        idx = parts.index("tests")
        first = parts[idx + 1]
    except (ValueError, IndexError):
        first = parts[-1]
    filename = parts[-1]
    if filename in _SECURITY_TEST_FILES:
        return "security"
    if filename in _RUNTIME_TEST_FILES:
        return "runtime"
    return _TEST_TIER_BY_PREFIX.get(first, "integration")


def pytest_collection_modifyitems(config, items):
    """Apply release-gate markers from test paths without moving files."""
    for item in items:
        tier = _tier_for_test_path(str(item.fspath))
        item.add_marker(pytest.mark.release)
        item.add_marker(getattr(pytest.mark, tier))
