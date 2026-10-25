"""Qt settings dialog: seven tabs, density persistence and draft/cancel semantics."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

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
