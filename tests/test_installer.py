# -*- coding: utf-8 -*-
"""Installer / entry-point validation tests."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestEntryPoint:
    """Verify the `nous` entry point is correctly generated."""

    def test_nous_help_works(self):
        """nous --help must return 0."""
        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main", "--help"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "nous" in r.stdout.lower() or "Usage" in r.stdout

    def test_nous_version_works(self):
        """nous version must return 0 and show version."""
        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main", "version"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "Runtime" in r.stdout

    def test_nous_doctor_works(self):
        """nous doctor must return 0 and show diagnostics."""
        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main", "doctor"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "Environment" in r.stdout or "Check" in r.stdout


class TestDoctorReport:
    """Verify doctor diagnostics cover all required areas."""

    def test_doctor_covers_runtime(self):
        """Doctor must check Runtime installation."""
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Runtime" in names, "Doctor missing Runtime check"

    def test_doctor_covers_workspace(self):
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Workspace" in names, "Doctor missing Workspace check"

    def test_doctor_covers_provider(self):
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Provider" in names, "Doctor missing Provider check"

    def test_doctor_covers_memory(self):
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Memory" in names, "Doctor missing Memory check"

    def test_doctor_covers_capabilities(self):
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Capabilities" in names, "Doctor missing Capabilities check"

    def test_doctor_covers_environment(self):
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        names = {c.name for c in report.checks}
        assert "Environment" in names, "Doctor missing Environment check"

    def test_doctor_has_suggestions_on_warn(self):
        """Warning checks must include recovery suggestions."""
        from nous_runtime.cli.doctor import run_diagnostics
        report = run_diagnostics()
        for c in report.checks:
            if c.status == "warn" and c.name in ("Provider", "Workspace"):
                assert c.suggestion, \
                    f"Check '{c.name}' is warn but has no suggestion"


class TestPackageMetadata:
    """Verify pyproject.toml is correctly configured."""

    def test_entry_point_defined(self):
        """pyproject.toml must define the nous console script."""
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "nous" in toml
        assert "nous_runtime.cli.main" in toml

    def test_version_defined(self):
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'version = "' in toml or "version =" in toml
