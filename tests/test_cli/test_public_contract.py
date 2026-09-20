# -*- coding: utf-8 -*-
"""Public CLI contract tests — every command must handle empty state cleanly."""

import subprocess
import sys
import os


def _nous(*args) -> subprocess.CompletedProcess:
    """Run `nous` CLI command."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main"] + list(args),
        capture_output=True, text=True, cwd=root, timeout=30,
    )


class TestHelpAndVersion:
    """nous --help and nous --version must work in any state."""

    def test_help_flag(self):
        r = _nous("--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "Usage" in r.stdout or "Commands" in r.stdout

    def test_version_command(self):
        r = _nous("version")
        assert r.returncode == 0
        assert "Nous Runtime" in r.stdout


class TestEmptyStateCommands:
    """All read-only commands must handle empty Runtime without crashing."""

    def test_doctor(self):
        r = _nous("doctor")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_status(self):
        r = _nous("status")
        assert r.returncode == 0

    def test_provider_list(self):
        r = _nous("provider", "list")
        assert r.returncode == 0
        assert "Error" not in r.stdout or "No providers" in r.stdout

    def test_capability_list(self):
        r = _nous("capability", "list")
        assert r.returncode == 0

    def test_pack_list(self):
        r = _nous("pack", "list")
        assert r.returncode == 0

    def test_trace(self):
        r = _nous("trace", "--limit", "3")
        assert r.returncode == 0

    def test_demo(self):
        r = _nous("demo")
        assert r.returncode == 0

    def test_pack_help(self):
        r = _nous("pack", "--help")
        assert r.returncode == 0

    def test_provider_help(self):
        r = _nous("provider", "--help")
        assert r.returncode == 0

    def test_capability_help(self):
        r = _nous("capability", "--help")
        assert r.returncode == 0

    def test_dev_help(self):
        r = _nous("dev", "--help")
        assert r.returncode == 0
