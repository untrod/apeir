# -*- coding: utf-8 -*-
"""Version consistency tests — single source of truth.

Validates that the canonical version in nous_runtime._version is the
single source of truth, and that all manifests and import paths are
consistent with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# Accept both stable and pre-release semver
# e.g. "1.0.0", "1.0.0-rc1", "1.0.0-rc.1", "0.1.1a0"
_VERSION_RE = re.compile(
    r"^\d+\.\d+\.\d+((\.dev\d+)|(a\d+)|(\-rc\d+)|(\-rc\.\d+))?$"
)


def test_version_module_exists():
    """version.py must exist and export __version__."""
    from nous_runtime.version import __version__
    assert __version__
    assert _VERSION_RE.match(__version__), f"Invalid semver: {__version__}"


def test_canonical_is_in_version_module():
    """_version.py must be the single source of truth."""
    from nous_runtime._version import __version__ as canonical
    from nous_runtime.version import __version__ as re_exported
    assert canonical == re_exported, (
        f"_version={canonical!r} != version={re_exported!r}"
    )


def test_init_imports_from_version():
    """nous_runtime.__version__ must come from nous_runtime.version."""
    from nous_runtime import __version__ as init_ver
    from nous_runtime.version import __version__ as src_ver
    assert init_ver == src_ver, f"Init: {init_ver} != Source: {src_ver}"


def test_pyproject_toml_consistent():
    """pyproject.toml version must match nous_runtime._version."""
    from nous_runtime._version import __version__

    toml_path = ROOT / "pyproject.toml"
    if not toml_path.is_file():
        pytest.skip("pyproject.toml not found")

    content = toml_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        toml_ver = match.group(1)
        assert toml_ver == __version__, (
            f"pyproject.toml: {toml_ver} != _version.py: {__version__}"
        )


def test_desktop_package_json_consistent():
    """desktop/package.json version must match."""
    from nous_runtime._version import __version__

    pkg_path = ROOT / "desktop" / "package.json"
    if not pkg_path.is_file():
        pytest.skip("desktop/package.json not found")

    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert data.get("version") == __version__, (
        f"desktop/package.json: {data.get('version')} != {__version__}"
    )


def test_cargo_toml_consistent():
    """desktop/src-tauri/Cargo.toml version must match."""
    from nous_runtime._version import __version__

    cargo_path = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
    if not cargo_path.is_file():
        pytest.skip("Cargo.toml not found")

    content = cargo_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        cargo_ver = match.group(1)
        assert cargo_ver == __version__, (
            f"Cargo.toml: {cargo_ver} != _version.py: {__version__}"
        )


def test_tauri_conf_json_consistent():
    """tauri.conf.json package.version must match."""
    from nous_runtime._version import __version__

    conf_path = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    if not conf_path.is_file():
        pytest.skip("tauri.conf.json not found")

    data = json.loads(conf_path.read_text(encoding="utf-8"))
    pkg_ver = data.get("version") or data.get("package", {}).get("version", "")
    assert pkg_ver == __version__, (
        f"tauri.conf.json: {pkg_ver} != {__version__}"
    )


def test_vscode_package_json_consistent():
    """ide/vscode/package.json version must match."""
    from nous_runtime._version import __version__

    pkg_path = ROOT / "ide" / "vscode" / "package.json"
    if not pkg_path.is_file():
        pytest.skip("ide/vscode/package.json not found")

    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert data.get("version") == __version__, (
        f"ide/vscode/package.json: {data.get('version')} != {__version__}"
    )


def test_sdk_package_json_consistent():
    """nous_runtime/sdk/package.json version must match."""
    from nous_runtime._version import __version__

    pkg_path = ROOT / "nous_runtime" / "sdk" / "package.json"
    if not pkg_path.is_file():
        pytest.skip("sdk/package.json not found")

    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert data.get("version") == __version__, (
        f"sdk/package.json: {data.get('version')} != {__version__}"
    )


def test_api_server_version_header():
    """API server must use NousRuntimeAPI/1.0."""
    server_py = ROOT / "nous_runtime" / "api" / "server.py"
    content = server_py.read_text(encoding="utf-8")
    assert 'server_version = "NousRuntimeAPI/1.0"' in content, (
        "server.py: expected server_version = 'NousRuntimeAPI/1.0'"
    )


def test_protocol_version_from_canonical():
    """Protocol PROTOCOL_VERSION must import from _version.py."""
    envelope_py = ROOT / "nous_runtime" / "connectivity" / "protocol" / "envelope.py"
    content = envelope_py.read_text(encoding="utf-8")
    assert "from nous_runtime._version import PROTOCOL_VERSION" in content, (
        "envelope.py must import PROTOCOL_VERSION from nous_runtime._version"
    )


def test_no_hardcoded_versions_in_cli():
    """CLI files must not hardcode version strings."""
    cli_dir = ROOT / "nous_runtime" / "cli"

    for filename in ["main.py", "shell_v2.py", "wizard.py"]:
        path = cli_dir / filename
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")

        # These files must import from version
        has_import = (
            "from nous_runtime.version import __version__" in content
            or "from nous_runtime._version import __version__" in content
            or "from nous_runtime.version import __version__ as _V" in content
        )
        if not has_import:
            # CLI files may import from __init__
            pass  # Not a hard requirement for all CLI files

        # Should NOT contain hardcoded version strings (except in import lines)
        lines = [
            line for line in content.split("\n")
            if "import" not in line and "__version__" not in line
        ]
        hardcoded = [
            line.strip()
            for line in lines
            if re.search(r'"v?\d+\.\d+\.\d+', line)
            or re.search(r"'v?\d+\.\d+\.\d+", line)
        ]
        assert not hardcoded, f"{filename}: hardcoded version found: {hardcoded}"


def test_rc1_version_format():
    """Version must indicate RC status during consolidation phase."""
    from nous_runtime._version import __version__, is_rc

    assert is_rc(), (
        f"Expected RC version (containing 'rc'), got {__version__}. "
        "Run tools/freeze_version.py to propagate."
    )
    assert "rc" in __version__
