# -*- coding: utf-8 -*-
"""Validate that all schema version constants are sourced from the central registry.

This test ensures:
1. Every SCHEMA_VERSION constant in the codebase matches the canonical registry value.
2. No module defines its own hardcoded SCHEMA_VERSION string/int.
3. The registry itself is consistent with _version.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# Helpers

def _find_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, excluding __pycache__ and .venv."""
    files: list[Path] = []
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts or ".venv" in p.parts:
            continue
        files.append(p)
    return files


def _extract_schema_assignments(filepath: Path) -> list[tuple[int, str, str]]:
    """Find lines that assign a hardcoded string/int to a SCHEMA_VERSION name.

    Returns list of (line_number, variable_name, assigned_value).
    """
    results: list[tuple[int, str, str]] = []
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and "SCHEMA_VERSION" in target.id:
                    if isinstance(node.value, ast.Constant):
                        val = repr(node.value.value)
                        results.append((node.lineno, target.id, val))
    return results


# Tests

class TestSchemaRegistryConsistency:
    """Validate the central schema registry."""

    def test_registry_importable(self):
        """Schema registry should be importable without side effects."""
        from nous_runtime import schema_registry
        assert schema_registry is not None

    def test_all_versions_are_string_or_int(self):
        """Every schema version constant must be str or int."""
        from nous_runtime.schema_registry import all_schema_versions

        versions = all_schema_versions()
        assert len(versions) > 10, "Expected at least 10 schema version constants"
        for name, value in versions.items():
            assert isinstance(value, (str, int)), (
                f"{name} = {value!r} has type {type(value).__name__}, expected str or int"
            )

    def test_canonical_values_match_version_module(self):
        """CANONICAL_SCHEMA_VERSION must match _version.py."""
        from nous_runtime._version import (
            CANONICAL_SCHEMA_VERSION,
            CANONICAL_SCHEMA_VERSION_SHORT,
            PROTOCOL_VERSION,
        )
        from nous_runtime.schema_registry import (
            CANONICAL_PROTOCOL_VERSION,
        )

        assert CANONICAL_SCHEMA_VERSION == "1.0.0"
        assert CANONICAL_SCHEMA_VERSION_SHORT == "1.0"
        assert PROTOCOL_VERSION == "1.0"
        assert CANONICAL_PROTOCOL_VERSION == PROTOCOL_VERSION

    def test_no_duplicate_constants(self):
        """No two schema constants should have the same name."""
        from nous_runtime.schema_registry import all_schema_versions

        versions = all_schema_versions()
        names = list(versions.keys())
        assert len(names) == len(set(names)), (
            f"Duplicate schema version names found: {[n for n in names if names.count(n) > 1]}"
        )


class TestNoHardcodedSchemaVersions:
    """Ensure no module defines its own hardcoded SCHEMA_VERSION."""

    # Files allowed to define SCHEMA_VERSION locally (protocol layer, registry itself)
    ALLOWED = {
        "schema_registry.py",    # The registry itself defines canonical values
        "_version.py",           # Canonical version authority
        "envelope.py",           # Protocol message format version
    }

    def test_nous_runtime_no_hardcoded_schemas(self):
        """No nous_runtime module should hardcode a SCHEMA_VERSION string."""
        runtime_dir = ROOT / "nous_runtime"
        violations: list[str] = []

        for py_file in _find_py_files(runtime_dir):
            fname = py_file.name
            if fname in self.ALLOWED:
                continue
            assignments = _extract_schema_assignments(py_file)
            for lineno, varname, value in assignments:
                violations.append(
                    f"{py_file.relative_to(ROOT)}:{lineno}: {varname} = {value}"
                )

        if violations:
            msg = (
                "The following modules define hardcoded SCHEMA_VERSION constants.\n"
                "Import from nous_runtime.schema_registry instead:\n\n"
                + "\n".join(f"  {v}" for v in violations)
            )
            pytest.fail(msg)

    def test_tests_no_hardcoded_schemas(self):
        """Test files should not define their own SCHEMA_VERSION either."""
        tests_dir = ROOT / "tests"
        violations: list[str] = []

        for py_file in _find_py_files(tests_dir):
            assignments = _extract_schema_assignments(py_file)
            for lineno, varname, value in assignments:
                violations.append(
                    f"{py_file.relative_to(ROOT)}:{lineno}: {varname} = {value}"
                )

        if violations:
            msg = (
                "Test files should not define hardcoded SCHEMA_VERSION:\n"
                + "\n".join(f"  {v}" for v in violations)
            )
            pytest.fail(msg)


class TestVersionConsistency:
    """Ensure all version strings match the canonical version."""

    def test_pyproject_toml_matches(self):
        """pyproject.toml version must match _version.py."""
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib

        from nous_runtime._version import __version__

        ppt = ROOT / "pyproject.toml"
        if not ppt.exists():
            pytest.skip("pyproject.toml not found")
        with open(ppt, "rb") as f:
            data = tomllib.load(f)
        project_version = data.get("project", {}).get("version", "")
        assert project_version == __version__, (
            f"pyproject.toml version={project_version!r} != {__version__!r}"
        )

    def test_desktop_package_json_matches(self):
        """desktop/package.json version must match."""
        import json

        from nous_runtime._version import __version__

        pkg = ROOT / "desktop" / "package.json"
        if not pkg.exists():
            pytest.skip("desktop/package.json not found")
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data.get("version") == __version__, (
            f"desktop/package.json version={data.get('version')!r} != {__version__!r}"
        )

    def test_tauri_conf_json_matches(self):
        """tauri.conf.json version must match."""
        import json

        from nous_runtime._version import __version__

        conf = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
        if not conf.exists():
            pytest.skip("tauri.conf.json not found")
        data = json.loads(conf.read_text(encoding="utf-8"))
        config_version = data.get("version") or data.get("package", {}).get("version")
        assert config_version == __version__, (
            f"tauri.conf.json version={config_version!r} != {__version__!r}"
        )

    def test_sdk_package_json_matches(self):
        """SDK package.json version must match."""
        import json

        from nous_runtime._version import __version__

        pkg = ROOT / "nous_runtime" / "sdk" / "package.json"
        if not pkg.exists():
            pytest.skip("sdk/package.json not found")
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data.get("version") == __version__, (
            f"sdk/package.json version={data.get('version')!r} != {__version__!r}"
        )

    def test_api_server_version(self):
        """API server version must reference v1."""
        server_py = ROOT / "nous_runtime" / "api" / "server.py"
        content = server_py.read_text(encoding="utf-8")
        assert 'server_version = "NousRuntimeAPI/1.0"' in content, (
            "server.py must use server_version = 'NousRuntimeAPI/1.0'"
        )
