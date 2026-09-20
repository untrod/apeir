"""Resolve runnable executables before governance binds the execution target."""

import shutil
import sys
from pathlib import Path


def resolve_executable(command: str) -> str | None:
    resolved = shutil.which(command)
    # Windows App Execution Aliases are reparse points, not VM-mappable runtimes.
    # Preserve explicit paths and real PATH-selected interpreters (including venvs).
    if (resolved and command.casefold() in {"python", "python.exe", "python3", "python3.exe"}
            and Path(resolved).parent.name.casefold() == "windowsapps"
            and not getattr(sys, "frozen", False)):
        interpreter = Path(sys.executable)
        if interpreter.is_file() and interpreter.parent.name.casefold() != "windowsapps":
            return str(interpreter.resolve())
    return resolved
