"""Run the frozen Kernel's own test entry in a dependency-isolated Python env.

This is build-environment separation, not a workload security sandbox. Native
Runtime/Kernel integration still runs separately with the real Distribution.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile
import venv


@contextmanager
def kernel_test_environment(
    parent: Mapping[str, str],
) -> Iterator[tuple[Path, dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix="apeir-kernel-tests-") as temporary:
        root = Path(temporary) / "python"
        venv.EnvBuilder(with_pip=False).create(root)
        scripts = root / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        environment = dict(parent)
        for name in ("PYTHONPATH", "PYTHONHOME"):
            environment.pop(name, None)
        environment.update(
            PATH=str(scripts) + os.pathsep + environment.get("PATH", ""),
            VIRTUAL_ENV=str(root),
            PYTHONNOUSERSITE="1",
        )
        yield python, environment


def run_kernel_tests(kernel: Path, powershell: Path) -> int:
    kernel = kernel.resolve(strict=True)
    entry = kernel / "scripts" / "test.ps1"
    if not entry.is_file():
        raise ValueError("Kernel source test entry is missing")
    with kernel_test_environment(os.environ) as (python, environment):
        # A regular installed Distribution package wins over the Kernel's
        # namespace fixture even when that fixture leads PYTHONPATH. Verify the
        # clean starting environment; the frozen test adds its own fixture path.
        subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.util; "
                "assert importlib.util.find_spec('nous_runtime') is None, "
                "'Distribution must not shadow the standalone Kernel fixture'",
            ],
            cwd=kernel,
            env=environment,
            check=True,
        )
        print("Kernel source tests: stdlib-only Python environment", flush=True)
        return subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(entry),
            ],
            cwd=kernel,
            env=environment,
            check=False,
        ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-root", type=Path, required=True)
    parser.add_argument("--powershell", type=Path, required=True)
    args = parser.parse_args()
    return run_kernel_tests(args.kernel_root, args.powershell.resolve(strict=True))


if __name__ == "__main__":
    raise SystemExit(main())
