from __future__ import annotations

import importlib.util

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import pytest

from nous_runtime.model_distribution.installer_gui import (
    run_gui_installer,
)
from nous_runtime.model_runtime import ModelResolutionError


def test_gui_module_is_lazy_when_qt_is_not_installed(tmp_path) -> None:
    if importlib.util.find_spec("PySide6") is not None:
        pytest.skip("PySide6 is installed; do not open a GUI in tests")
    with pytest.raises(ModelResolutionError, match="PySide6"):
        run_gui_installer(tmp_path / ".nous")


def test_gui_entry_and_optional_dependencies_are_declared() -> None:
    with open("pyproject.toml", "rb") as stream:
        project = tomllib.load(stream)["project"]
    assert project["gui-scripts"]["nous-installer"].endswith(
        "installer_gui:main"
    )
    assert any(
        requirement.startswith("PySide6")
        for requirement in project["optional-dependencies"]["installer"]
    )
