"""Qt application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from ..config import Settings
from .main_window import MainWindow

_ICON_PATH = Path(__file__).resolve().parent.parent / "ui" / "assets" / "app.ico"


def run(settings: Settings) -> int:
    """Create the Qt application, show the main window and run the event loop."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setOrganizationName("FPSPatcherStudio")
    app.setApplicationDisplayName(APP_NAME)
    if _ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))

    window = MainWindow(settings)
    window.show()
    return app.exec()


def main() -> int:
    return run(Settings.load())
