"""Qt accessibility parity: target sizes, focus ring, contrast and app font."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFontInfo  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui_qt.qss import apply_theme, build_qss  # noqa: E402
from fps_patcher.ui_qt.theme import (  # noqa: E402
    PRESETS,
    UI_FONT_FAMILIES,
    load_qt_fonts,
    make_theme,
)


def _luminance(color: str) -> float:
    raw = color.lstrip("#")
    channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_clickable_targets_and_primary_buttons_are_large_enough(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    buttons = window.findChildren(QPushButton)
    assert buttons

    for button in buttons:
        assert button.width() >= 26, button.text()
        assert button.height() >= 26, button.text()

    assert window.inspector.start_btn.height() >= 36
    assert window.inspector.cancel_btn.height() >= 28
    window.close()


def test_icon_only_buttons_have_accessible_names(
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
        assert button.accessibleName().strip()
        assert button.toolTip().strip()
        assert button.width() >= 26 and button.height() >= 26
    window.close()


def test_focus_ring_uses_two_pixel_border_focus() -> None:
    theme = make_theme(Settings())
    qss = build_qss(theme)
    assert f"border: 2px solid {theme.color('border_focus')}" in qss
    assert 'QPushButton:focus' in qss


def test_app_font_resolves_to_inter_or_a_fallback_ui_face(qapp: QApplication) -> None:
    loaded = load_qt_fonts()
    assert "Inter" in loaded
    apply_theme(qapp, make_theme(Settings(font_size="M")))

    requested = qapp.font().families()
    assert requested and requested[0] == "Inter"
    resolved = QFontInfo(qapp.font()).family()
    assert resolved in set(UI_FONT_FAMILIES) or resolved == "Inter"
    assert qapp.font().pixelSize() == 13


def test_text_and_muted_contrast_on_bg_and_surface_for_all_presets() -> None:
    for name, tokens in PRESETS.items():
        for index, mode in enumerate(("light", "dark")):
            for foreground in ("text", "text2", "muted"):
                for background in ("bg", "surface"):
                    ratio = _contrast(
                        getattr(tokens, foreground)[index], getattr(tokens, background)[index]
                    )
                    assert ratio >= 4.5, f"{name} {mode} {foreground}/{background} = {ratio:.2f}"
