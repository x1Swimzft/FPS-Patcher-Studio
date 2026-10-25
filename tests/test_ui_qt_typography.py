"""Qt typography parity with the pinned Tk design tokens (offscreen, no window)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt.console import ConsolePanel  # noqa: E402
from fps_patcher.ui_qt.inspector import Inspector  # noqa: E402
from fps_patcher.ui_qt.theme import FONT_SIZE_SCALES, ThemeManager, make_theme  # noqa: E402

EMOJI = ("\u26a1", "\u2728", "\U0001f680", "\U0001f525", "\U0001f3ac", "\U0001f3af")


def _inside_warn_callout(label: QLabel) -> bool:
    parent = label.parentWidget()
    while parent is not None:
        if parent.objectName() == "WarnCallout":
            return True
        parent = parent.parentWidget()
    return False


def test_make_theme_font_scale_contract() -> None:
    medium = make_theme(Settings(font_size="M"))
    assert (medium.fonts.body, medium.fonts.caption, medium.fonts.badge) == (13, 12, 11)
    assert 11 <= medium.fonts.mono <= 12
    assert medium.fonts.thai_line_height_extra > 0

    small = make_theme(Settings(font_size="S"))
    assert (small.fonts.body, small.fonts.caption, small.fonts.badge) == (12, 11, 10)
    assert small.fonts.mono == 11

    large = make_theme(Settings(font_size="L"))
    assert (large.fonts.body, large.fonts.caption, large.fonts.badge) == (15, 14, 13)
    assert large.fonts.mono == 13

    assert all(scale.thai_line_height_extra > 0 for scale in FONT_SIZE_SCALES.values())


@pytest.mark.parametrize("lang", ["en", "th"])
def test_inspector_start_button_text_has_no_emoji(qtbot: Any, lang: str) -> None:
    settings = Settings(language=lang)
    inspector = Inspector(settings, ThemeManager(settings))
    qtbot.addWidget(inspector)

    expected = t("start_patch", lang)
    assert inspector.start_btn.text() == expected
    for character in EMOJI:
        assert character not in inspector.start_btn.text()


def test_inspector_qt_font_pixel_sizes(qtbot: Any) -> None:
    settings = Settings(font_size="M")
    theme = make_theme(settings)
    inspector = Inspector(settings, ThemeManager(settings))
    qtbot.addWidget(inspector)

    # The stylesheet resolves body text to the same 13 px as the Tk theme.
    assert inspector.font().pixelSize() == theme.fonts.body
    assert f"font-size: {theme.fonts.body}px" in inspector.styleSheet()

    for button in inspector.findChildren(QPushButton):
        assert button.font().pixelSize() >= theme.fonts.body, button.text()

    caption_roles = {"caption", "cardCaption", "muted"}
    for label in inspector.findChildren(QLabel):
        pixels = label.font().pixelSize()
        role = label.property("role")
        if role in caption_roles or _inside_warn_callout(label):
            assert pixels >= theme.fonts.caption, label.text()
        else:
            assert pixels >= theme.fonts.body, label.text()


def test_console_mono_font_pixel_sizes(qtbot: Any) -> None:
    for size in (11, 12):
        settings = Settings(console_font_size=size)
        console = ConsolePanel(settings, ThemeManager(settings))
        qtbot.addWidget(console)
        assert console.editor.font().pixelSize() >= 11
        assert console._latest.font().pixelSize() >= 11
