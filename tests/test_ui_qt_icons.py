"""Qt icon assets, QIcon loading and icon-only button accessibility."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from fps_patcher.ui_qt.icons import get_icon, icon_path  # noqa: E402

UI_QT_SRC = Path(__file__).resolve().parent.parent / "src" / "fps_patcher" / "ui_qt"
ASSETS = Path(__file__).resolve().parent.parent / "src" / "fps_patcher" / "ui" / "assets"
# "info" is the new button-glyph asset; the rest are literal calls in ui_qt.
EXTRA_ICONS = {"info"}


def _ui_qt_icon_names() -> set[str]:
    names: set[str] = set()
    for source in UI_QT_SRC.glob("*.py"):
        for line in source.read_text(encoding="utf-8").splitlines():
            if "get_icon(" in line or "icon_button(" in line:
                names.update(re.findall(r'"([a-z_]+)"', line))
    return names


def test_every_used_icon_has_light_and_dark_32px_assets(qapp: Any) -> None:
    names = _ui_qt_icon_names() | EXTRA_ICONS
    assert {"chevron_down", "chevron_right", "folder", "more", "settings", "sun"} <= names
    assert "info" in names

    for name in sorted(names):
        for dark in (False, True):
            path = icon_path(name, dark)
            assert path.is_file(), f"Missing icon asset: {path.name}"
            with Image.open(path) as image:
                assert image.size == (32, 32), path.name
                assert image.mode == "RGBA", path.name
                assert image.getchannel("A").getbbox() is not None, path.name


def test_get_icon_returns_qt_icon_or_null(qapp: Any) -> None:
    for name in sorted(_ui_qt_icon_names() | EXTRA_ICONS):
        for dark in (False, True):
            assert not get_icon(name, dark).isNull(), (name, dark)

    assert get_icon("this_icon_does_not_exist", False).isNull()
    assert get_icon("this_icon_does_not_exist", True).isNull()


def test_main_window_icon_buttons_have_name_tooltip_and_target_size(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    icon_buttons = [
        button
        for button in window.findChildren(QPushButton)
        if button.property("variant") == "icon"
    ]
    assert icon_buttons
    for button in icon_buttons:
        assert button.toolTip(), "icon-only button must have a tooltip"
        assert button.accessibleName(), "icon-only button must have an accessible name"
        assert button.width() >= 26, button.toolTip()
        assert button.height() >= 26, button.toolTip()
    window.close()
