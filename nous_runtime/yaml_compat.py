"""Architecture-safe PyYAML import.

Some Windows ARM64 PyYAML wheels expose a native ``yaml._yaml`` extension that
can raise an uncatchable illegal-instruction fault during import. Configuration
workloads do not need the C accelerator, so ARM hosts deliberately preload an
empty ``yaml.cyaml`` module and use PyYAML's pure Python Loader/Dumper classes.
"""

from __future__ import annotations

import importlib
import platform
import sys
import types


def _requires_pure_python() -> bool:
    machine = platform.machine().strip().lower()
    return machine in {"arm64", "aarch64"} or (
        sys.platform == "win32" and "arm" in machine
    )


if _requires_pure_python() and "yaml" not in sys.modules:
    sys.modules.setdefault("yaml.cyaml", types.ModuleType("yaml.cyaml"))

yaml = importlib.import_module("yaml")


__all__ = ["yaml"]
