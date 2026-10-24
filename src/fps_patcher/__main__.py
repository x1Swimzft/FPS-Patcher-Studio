"""Entry point: ``python -m fps_patcher`` or ``fps-patcher-studio``."""

from __future__ import annotations

import contextlib
import ctypes
import sys
from pathlib import Path

from fps_patcher import APP_USER_MODEL_ID
from fps_patcher.config import Settings


def _quick_patch_target(argv: list[str]) -> str | None:
    """Return the --quick-patch path, "" for a bad invocation, or None for GUI mode."""
    try:
        index = argv.index("--quick-patch")
    except ValueError:
        return None
    if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
        return ""
    return argv[index + 1]


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    target = _quick_patch_target(args)
    if target is not None:
        from fps_patcher.logging_setup import setup_logging

        setup_logging()
        if not target:
            print("usage: fps-patcher-studio --quick-patch <video>", file=sys.stderr)
            raise SystemExit(2)
        from fps_patcher.app.quick_patch import run

        raise SystemExit(run(Path(target)))

    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    from fps_patcher.logging_setup import setup_logging

    setup_logging()
    from fps_patcher.ui.main_window import MainWindow  # deferred: Tk import only when launching UI

    MainWindow(Settings.load()).mainloop()


if __name__ == "__main__":
    main()
