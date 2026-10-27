"""Dependency separation for frozen-source validation, not Kernel simulation."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.ci.run_kernel_source_tests import kernel_test_environment, run_kernel_tests


def test_kernel_environment_keeps_fixture_namespace_and_parent_unchanged(tmp_path):
    installed = tmp_path / "installed"
    fixture = tmp_path / "fixture"
    regular = installed / "apeir_build_probe"
    namespace = fixture / "apeir_build_probe"
    regular.mkdir(parents=True)
    namespace.mkdir(parents=True)
    (regular / "__init__.py").write_text("origin = 'installed'\n")
    (namespace / "probe.py").write_text("origin = 'kernel-fixture'\n")
    # A regular package takes precedence over a namespace, even behind it.
    contaminated = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(map(str, (fixture, installed))),
    }
    result = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import apeir_build_probe; print(apeir_build_probe.origin)",
        ],
        cwd=tmp_path,
        env=contaminated,
        text=True,
    )
    assert result.strip() == "installed"
    parent = {
        **contaminated,
        "PYTHONHOME": "not-a-valid-python-home",
        "VIRTUAL_ENV": "parent-environment",
        "PYTHONNOUSERSITE": "0",
        "APEIR_BUILD_PROBE": "preserved",
    }
    original = dict(parent)
    with kernel_test_environment(parent) as (python, environment):
        assert "PYTHONPATH" not in environment
        assert "PYTHONHOME" not in environment
        assert environment["VIRTUAL_ENV"] != parent["VIRTUAL_ENV"]
        assert environment["PYTHONNOUSERSITE"] == "1"
        assert environment["APEIR_BUILD_PROBE"] == "preserved"
        subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.util; assert importlib.util.find_spec('nous_runtime') is None",
            ],
            cwd=tmp_path,
            env=environment,
            check=True,
        )
        # The original suite is responsible for selecting its fixture.
        selected = {**environment, "PYTHONPATH": str(fixture)}
        result = subprocess.check_output(
            [
                str(python),
                "-c",
                "from apeir_build_probe.probe import origin; print(origin)",
            ],
            cwd=tmp_path,
            env=selected,
            text=True,
        )
        assert result.strip() == "kernel-fixture"
    assert parent == original
    assert not python.exists()


def test_kernel_environment_cleans_up_after_failure():
    original = dict(os.environ)
    with pytest.raises(RuntimeError, match="qualification failed"):
        with kernel_test_environment(original) as (python, _):
            assert python.exists()
            raise RuntimeError("qualification failed")
    assert not python.exists()
    assert dict(os.environ) == original


def test_kernel_qualification_refuses_a_shadow_package_in_its_working_directory(
    tmp_path,
):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "test.ps1").write_text("exit 0\n")
    shadow = tmp_path / "nous_runtime"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("# Unexpected package in the source tree.\n")
    with pytest.raises(subprocess.CalledProcessError):
        # This executable must never be invoked: Python admission fails first.
        run_kernel_tests(tmp_path, tmp_path / "must-not-run")


@pytest.mark.parametrize("exit_code", [0, 17])
def test_original_powershell_entry_keeps_exit_status_and_parent_state(
    tmp_path, exit_code
):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is required for original Windows test-entry invocation")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "test.ps1").write_text(
        '& python -c "import importlib.util,sys; '
        "assert sys.prefix != sys.base_prefix; "
        "assert importlib.util.find_spec('nous_runtime') is None" + '"\n'
        "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        f"exit {exit_code}\n"
    )
    original_environment = dict(os.environ)
    original_directory = Path.cwd()
    assert run_kernel_tests(tmp_path, Path(powershell)) == exit_code
    assert dict(os.environ) == original_environment
    assert Path.cwd() == original_directory
