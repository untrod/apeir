"""Optional graphical entry point for the recoverable model installer."""

from __future__ import annotations

import sys
from pathlib import Path

from nous_runtime.model_distribution.installer import (
    ModelInstallerController,
)
from nous_runtime.model_runtime.errors import ModelResolutionError


def run_gui_installer(install_root: str | Path = ".nous") -> int:
    """Launch the PySide6 installer without making Qt a core dependency."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise ModelResolutionError(
            "PySide6 is required for the GUI installer; "
            "install nous-runtime[installer]"
        ) from exc

    from nous_runtime.model_distribution.qt_wizard import (
        create_installer_wizard,
    )

    controller = ModelInstallerController(install_root)
    controller.prepare()
    application = QApplication.instance() or QApplication(sys.argv)
    wizard = create_installer_wizard(controller)
    result = wizard.exec()
    if QApplication.instance() is application:
        application.processEvents()
    return int(result)


def main() -> int:
    return run_gui_installer()


__all__ = ["main", "run_gui_installer"]
