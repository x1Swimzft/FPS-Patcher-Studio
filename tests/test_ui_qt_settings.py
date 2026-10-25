"""Qt settings dialog: seven tabs, density persistence and draft/cancel semantics."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QWidget,
)

from fps_patcher import config  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


@pytest.fixture
def appdata(monkeypatch: Any, tmp_path: Path) -> Path:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    return tmp_path


def _dialog(qtbot: Any, settings: Settings) -> SettingsDialog:
    dialog = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(dialog)
    return dialog


def _show(dialog: SettingsDialog) -> None:
    dialog.show()
    QApplication.processEvents()
    dialog.layout().activate()
    QApplication.processEvents()


def test_dialog_size_and_footer_alignment(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(qtbot, Settings(reduce_motion=True))
    _show(dialog)

    assert (dialog.width(), dialog.height()) == (920, 640)
    assert (dialog.minimumWidth(), dialog.minimumHeight()) == (820, 560)

    footer = dialog.findChild(QWidget, "SettingsFooter")
    assert footer is not None
    assert footer.height() == 52
    assert footer.layout().contentsMargins().left() == 20
    assert footer.layout().contentsMargins().top() == 10
    assert footer.layout().spacing() == 8

    assert dialog._reset_btn.objectName() == "SettingsFooterButton"
    assert dialog._cancel_btn.objectName() == "SettingsFooterButton"
    assert dialog._apply_btn.objectName() == "SettingsFooterButton"
    assert dialog._ok_btn.objectName() == "SettingsPrimaryButton"
    buttons = (dialog._reset_btn, dialog._cancel_btn, dialog._apply_btn, dialog._ok_btn)
    assert all(button.height() == 32 for button in buttons)
    assert len({button.height() for button in buttons}) == 1
    assert (
        dialog._ok_btn.geometry().top()
        == dialog._cancel_btn.geometry().top()
        == dialog._apply_btn.geometry().top()
    )
    assert dialog._ok_btn.geometry().top() == dialog._reset_btn.geometry().top()


def test_sidebar_search_filters_and_shows_empty_state(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(qtbot, Settings(reduce_motion=True))
    _show(dialog)

    rail = dialog.findChild(QFrame, "SettingsRail")
    assert rail is not None
    assert rail.width() == 210
    assert dialog._search.placeholderText() == dialog._tr("settings_search_placeholder")
    assert dialog._search.height() == 28
    for button in dialog._nav_buttons.values():
        assert button.objectName() == "SettingsNavPill"
        assert button.height() == 34

    dialog._search.setText("FFmpeg")
    assert dialog._stack.currentWidget() is dialog._search_scroll
    matching = [row for row, _text in dialog._search_rows if row.isVisible()]
    assert matching
    assert not dialog._search_empty.isVisible()

    dialog._search.setText("definitely-no-such-setting")
    assert dialog._search_empty.isVisible()
    assert not any(row.isVisible() for row, _text in dialog._search_rows)

    dialog._search.clear()
    assert dialog._stack.currentWidget() is dialog._pages[0][2]


def test_seven_preset_swatches_select_and_preview(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(qtbot, Settings(reduce_motion=True))
    _show(dialog)

    cards = dialog.findChildren(QFrame, "PresetSwatchCard")
    assert len(cards) == 7
    assert set(dialog._preset_cards) == set(dialog._preset.itemText(i) for i in range(7))
    assert sum(card.property("selected") == "true" for card in cards) == 1
    assert all(len(card.dots) == 3 for card in cards)

    graphite = dialog._preset_cards["Graphite"]
    qtbot.mouseClick(graphite, Qt.MouseButton.LeftButton)

    assert dialog._draft.theme_preset == "Graphite"
    assert dialog._theme_manager.theme.tokens.name == "Graphite"
    assert graphite.property("selected") == "true"


def test_dialog_has_seven_tabs_and_density_control(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(qtbot, Settings(reduce_motion=True))

    assert [page[0] for page in dialog._pages] == [key for key, _label in SettingsDialog._TABS]
    assert len(dialog._pages) == 7
    assert len(dialog._nav_buttons) == 7
    assert dialog._density_labels == ["Compact", "Comfortable"]
    assert dialog._density.value in dialog._density_labels


def test_density_writes_layout_density_and_roundtrips(qtbot: Any, appdata: Path) -> None:
    settings = Settings(reduce_motion=True, layout_density="Compact")
    dialog = _dialog(qtbot, settings)

    dialog._density.set_value(dialog._density_labels[1])
    assert dialog._draft.layout_density == "Comfortable"

    dialog._apply()
    assert settings.layout_density == "Comfortable"
    saved = Settings.load(appdata / "settings.json")
    assert saved.layout_density == "Comfortable"


def test_legacy_json_applies_all_keys_and_cancel_restores_theme(
    qtbot: Any, appdata: Path
) -> None:
    legacy = {
        "ffmpeg_dir": "C:/ffmpeg",
        "output_dir": "D:/out",
        "last_preset": "120 FPS",
        "strategy": "bxd-bypass",
    }
    path = appdata / "settings.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    settings = Settings.load(path)
    assert settings.theme_preset == "Obsidian"
    manager = ThemeManager(settings)
    dialog = SettingsDialog(settings, manager)
    qtbot.addWidget(dialog)

    dialog._apply()

    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {item.name for item in fields(Settings) if item.init}
    assert set(payload) == expected_keys
    assert payload["layout_density"] == "Compact"
    assert payload["theme_preset"] == "Obsidian"

    # Preview a different preset/mode, then Cancel: the live theme must snap back.
    dialog._preset.setCurrentText("Graphite")
    dialog._appearance.set_value(dialog._appearance_labels[1])
    assert manager.theme.tokens.name == "Graphite"
    assert manager.theme.mode == "light"

    dialog.reject()

    assert manager.theme.tokens.name == "Obsidian"
    assert manager.theme.mode == "dark"
    assert settings.theme_preset == "Obsidian"
    assert settings.appearance == "dark"


def test_full_v2_settings_roundtrip(qtbot: Any, appdata: Path) -> None:
    settings = Settings(
        theme_preset="Graphite",
        appearance="light",
        custom_accent="#123456",
        layout_density="Comfortable",
        font_size="L",
        radius_style="Sharp",
        language="th",
        console_font_size=13,
        max_log_lines=1234,
        reduce_motion=True,
    )
    path = appdata / "settings.json"
    settings.save(path)

    loaded = Settings.load(path)
    assert loaded == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {item.name for item in fields(Settings) if item.init}

    dialog = SettingsDialog(loaded, ThemeManager(loaded))
    qtbot.addWidget(dialog)
    dialog._font_size.setCurrentText("M")
    dialog._density.set_value(dialog._density_labels[0])
    dialog._apply()

    reloaded = Settings.load(path)
    assert reloaded.font_size == "M"
    assert reloaded.layout_density == "Compact"
    assert reloaded.theme_preset == "Graphite"
