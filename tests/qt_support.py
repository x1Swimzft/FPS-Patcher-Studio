"""Shared helpers for the offscreen Qt test modules.

Every helper here keeps tests away from the real %APPDATA% folder, the network,
worker threads and the HKCU Explorer verb so a MainWindow can be built cheaply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fps_patcher import config
from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.ui_qt import main_window as mw


def isolate_app_data(monkeypatch: Any, tmp_path: Path) -> Path:
    """Point every app-data writer at ``tmp_path`` instead of real APPDATA."""
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mw, "app_data_dir", lambda: tmp_path)
    return tmp_path


def stub_startup(monkeypatch: Any) -> None:
    """Disable network, watcher, FFmpeg, Explorer and DWM startup side effects."""
    monkeypatch.setattr(
        AppController, "check_for_updates_background", lambda self, *args, **kwargs: None
    )
    monkeypatch.setattr(Settings, "save_async", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(mw, "update_title_bar_theme", MagicMock(return_value=True))
    monkeypatch.setattr(mw, "apply_backdrop", MagicMock(return_value=False))
    for name in (
        "_cleanup_stale_preflight",
        "_init_ffmpeg",
        "_sync_explorer_menu",
        "_sync_watcher",
    ):
        monkeypatch.setattr(mw.MainWindow, name, lambda self: None)


def make_main_window(
    qtbot: Any, monkeypatch: Any, tmp_path: Path, **overrides: Any
) -> mw.MainWindow:
    """Build a MainWindow with startup side effects off and isolated storage."""
    isolate_app_data(monkeypatch, tmp_path)
    stub_startup(monkeypatch)
    options: dict[str, Any] = {"remember_geometry": False, "reduce_motion": True}
    options.update(overrides)
    window = mw.MainWindow(Settings(**options))
    qtbot.addWidget(window)
    return window
