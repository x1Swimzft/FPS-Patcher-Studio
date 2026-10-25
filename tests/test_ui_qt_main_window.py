"""Qt main window shell: metrics, theme toggle, presets, Thai and settings apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QWidget  # noqa: E402

from fps_patcher.config import THEME_PRESETS  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import main_window as mw  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402


def test_default_window_metrics(qtbot: Any, monkeypatch: Any, tmp_path: Path) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)

    assert (window.width(), window.height()) == (1040, 700)
    assert (window.minimumWidth(), window.minimumHeight()) == (880, 600)

    toolbar = window.findChild(QWidget, "Toolbar")
    assert toolbar is not None
    assert toolbar.height() == 44

    assert window.inspector.width() == 300
    assert window.console.height() == 36

    window.console.set_expanded(True)
    assert window.console.height() == 180
    window.console.set_expanded(False)
    assert window.console.height() == 36

    window.close()


def test_settings_dialog_apply_updates_theme_and_density(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    dialog = SettingsDialog(window.settings, window.theme_manager, window)
    qtbot.addWidget(dialog)
    dialog.applied.connect(window._on_settings_applied)

    dialog._preset.setCurrentText("Graphite")
    dialog._density.set_value(dialog._density_labels[1])
    dialog._apply()

    assert window.settings.theme_preset == "Graphite"
    assert window.settings.layout_density == "Comfortable"
    assert window.theme.tokens.name == "Graphite"
    assert window.theme.density.name == "Comfortable"
    assert window.theme.outer == 6
    window.close()


def test_theme_toggle_changes_mode_and_calls_dwm(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    dwm = MagicMock(return_value=True)
    monkeypatch.setattr(mw, "update_title_bar_theme", dwm)
    original_mode = window.theme.mode

    window._toggle_appearance()

    assert window.theme.mode != original_mode
    assert window.theme.mode == window.settings.appearance
    assert dwm.called
    window.close()


def test_thai_language_constructs(qtbot: Any, monkeypatch: Any, tmp_path: Path) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, language="th")

    assert window.inspector.start_btn.text() == t("start_patch", "th")
    assert window.inspector.cancel_btn.text() == t("cancel_btn", "th")
    assert window.console._title.text() == t("activity_console", "th")
    window.close()


def test_language_switch_retranslates_live(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, language="en")
    window.settings.language = "th"
    window.theme_manager.apply(window.settings)

    assert window.inspector.start_btn.text() == t("start_patch", "th")
    assert window.console._title.text() == t("activity_console", "th")
    assert window.queue_view.add_files_button.text() == t("add_files_btn", "th")
    window.close()


@pytest.mark.parametrize("preset", THEME_PRESETS)
def test_all_seven_presets_construct(
    qtbot: Any, monkeypatch: Any, tmp_path: Path, preset: str
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, theme_preset=preset)
    assert window.theme.tokens.name == preset
    window.close()
