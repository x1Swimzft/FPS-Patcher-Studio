"""Entry point: ``python -m fps_patcher`` or ``fps-patcher-studio``."""

from __future__ import annotations

import contextlib
import ctypes
import os
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


def _select_ui(argv: list[str]) -> tuple[str, list[str]]:
    """Return (ui, argv without --ui): --ui wins over FPS_PATCHER_UI, else Qt."""
    ui = os.environ.get("FPS_PATCHER_UI", "qt").strip().lower() or "qt"
    rest: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "--ui":
            if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                ui = argv[index + 1].strip().lower()
                index += 2
            else:
                index += 1
            continue
        rest.append(argv[index])
        index += 1
    return ("tk" if ui == "tk" else "qt"), rest


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

    ui, args = _select_ui(args)
    if argv is None:
        sys.argv[1:] = args

    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    from fps_patcher.logging_setup import setup_logging

    setup_logging()
    if ui == "tk":
        # Legacy Tk UI for comparison. Qt 6 manages DPI itself, so only Tk opts in here.
        if sys.platform == "win32":
            with contextlib.suppress(AttributeError, OSError):
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
        from fps_patcher.ui.main_window import MainWindow

        MainWindow(Settings.load()).mainloop()
        return
    from fps_patcher.ui_qt.app import run as run_qt

    raise SystemExit(run_qt(Settings.load()))


if __name__ == "__main__":
    main()
