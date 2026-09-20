"""Focused packaging and CLI-entry regression tests."""

from __future__ import annotations

import os
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path

from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_project_script_targets_authoritative_cli():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["scripts"]["nous"] == "nous_runtime.cli.main:app"
    assert metadata["project"]["version"] == __version__
    assert callable(app)


def test_version_option_and_command_are_coherent():
    runner = CliRunner()

    option = runner.invoke(app, ["--version"])
    assert option.exit_code == 0
    assert option.stdout.strip() == f"Nous Runtime v{__version__}"

    command = runner.invoke(app, ["version"])
    assert command.exit_code == 0
    assert command.stdout.strip() == f"Nous Runtime v{__version__}"


def test_python_module_fallback_reports_version(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime", "--version"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"Nous Runtime v{__version__}"


def test_demo_overrides_legacy_console_encoding(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONIOENCODING"] = "gbk"

    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime", "demo"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("gbk", errors="replace")
    assert "Demo complete!" in result.stdout.decode("gbk")
