"""Entry point: ``python -m fps_patcher`` or ``fps-patcher-studio``."""

from __future__ import annotations

import contextlib
import ctypes
import sys

from fps_patcher import APP_USER_MODEL_ID
from fps_patcher.config import Settings
from fps_patcher.logging_setup import setup_logging


def main() -> None:
    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    setup_logging()
    from fps_patcher.ui.main_window import MainWindow  # deferred: Tk import only when launching UI

    MainWindow(Settings.load()).mainloop()


if __name__ == "__main__":
    main()
