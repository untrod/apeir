# -*- coding: utf-8 -*-
"""Pack lifecycle CLI tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _nous(*args, cwd=None, registry_file: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["NOUS_PACK_REGISTRY_FILE"] = str(registry_file)
    return subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or ROOT,
        env=env,
        timeout=30,
    )


def _create_pack(tmp_path: Path, registry_file: Path) -> Path:
    result = _nous(
        "dev",
        "new",
        "pack",
        "test_lifecycle",
        "--output",
        str(tmp_path),
        registry_file=registry_file,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return tmp_path / "test_lifecycle"


class TestPackLifecycle:
    """Each lifecycle assertion uses an isolated registry and setup."""

    def test_create_pack(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        assert pack_path.is_dir()

    def test_validate_pack(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        result = _nous(
            "dev",
            "validate",
            "--path",
            str(pack_path),
            registry_file=registry_file,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "valid" in result.stdout.lower()

    def test_install_pack(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        result = _nous(
            "pack",
            "install",
            str(pack_path),
            registry_file=registry_file,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_list_after_install(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        install = _nous(
            "pack",
            "install",
            str(pack_path),
            registry_file=registry_file,
        )
        assert install.returncode == 0, f"stderr: {install.stderr}"

        result = _nous("pack", "list", registry_file=registry_file)
        assert result.returncode == 0
        assert "test_lifecycle" in result.stdout

    def test_remove_pack(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        install = _nous(
            "pack",
            "install",
            str(pack_path),
            registry_file=registry_file,
        )
        assert install.returncode == 0, f"stderr: {install.stderr}"

        result = _nous(
            "pack",
            "remove",
            "test_lifecycle",
            registry_file=registry_file,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_list_after_remove(self, tmp_path):
        registry_file = tmp_path / "registry.json"
        pack_path = _create_pack(tmp_path, registry_file)
        install = _nous(
            "pack",
            "install",
            str(pack_path),
            registry_file=registry_file,
        )
        assert install.returncode == 0, f"stderr: {install.stderr}"
        remove = _nous(
            "pack",
            "remove",
            "test_lifecycle",
            registry_file=registry_file,
        )
        assert remove.returncode == 0, f"stderr: {remove.stderr}"

        result = _nous("pack", "list", registry_file=registry_file)
        assert result.returncode == 0
        assert "test_lifecycle" not in result.stdout