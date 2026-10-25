"""Theme token, density, settings and QSS contract tests (no window needed)."""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path

from PySide6.QtGui import QPalette

from fps_patcher.config import LAYOUT_DENSITIES, THEME_PRESETS, Settings
from fps_patcher.ui_qt.qss import build_palette, build_qss
from fps_patcher.ui_qt.theme import (
    CORNER_RADII,
    DENSITY_METRICS,
    FONT_SIZE_SCALES,
    PRESETS,
    ThemeManager,
    hex_to_colorref,
    make_theme,
)

HEX_PAIR = re.compile(r"^#[0-9A-Fa-f]{6}$")
CRIMSON_DARK = {
    "bg": "#0a0a0f",
    "surface": "#111118",
    "surface_raised": "#191923",
    "surface_hover": "#232334",
    "border": "#242432",
    "text": "#ecebf2",
    "text2": "#c9c8d6",
    "muted": "#9a99ab",
    "accent": "#c8283f",
    "accent_hover": "#d93049",
    "accent_light": "#ff5a70",
    "accent_glow": "#ff5a70",
    "accent_pressed": "#a91f33",
    "accent_dim": "#2a1119",
    "accent_dim_border": "#6b1f30",
    "toolbar_bg": "#0d0d13",
    "inspector_bg": "#0d0d13",
    "console_bg": "#07070b",
}


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


def test_all_presets_exist_and_are_opaque_hex_pairs() -> None:
    assert set(PRESETS) == set(THEME_PRESETS)
    assert len(PRESETS) == 7
    for name, tokens in PRESETS.items():
        assert tokens.name == name
        for token in fields(tokens):
            if token.name == "name":
                continue
            pair = getattr(tokens, token.name)
            assert isinstance(pair, tuple) and len(pair) == 2, f"{name}.{token.name}"
            for color in pair:
                assert HEX_PAIR.match(color), f"{name}.{token.name}: {color!r}"


def test_crimson_dark_profile_is_exact() -> None:
    tokens = PRESETS["Crimson Gamer"]
    for token_name, expected in CRIMSON_DARK.items():
        assert getattr(tokens, token_name)[1] == expected, token_name
    assert tokens.accent[0] == "#c8283f"


def test_density_corner_and_font_scale_values() -> None:
    assert LAYOUT_DENSITIES == ["Compact", "Comfortable"]

    compact = DENSITY_METRICS["Compact"]
    comfortable = DENSITY_METRICS["Comfortable"]
    assert (compact.outer, compact.inner, compact.spacing) == (4, 6, 8)
    assert (comfortable.outer, comfortable.inner, comfortable.spacing) == (6, 10, 12)

    assert (CORNER_RADII["Sharp"].card, CORNER_RADII["Sharp"].control) == (4, 4)
    assert (CORNER_RADII["Normal"].card, CORNER_RADII["Normal"].control) == (12, 8)
    assert (CORNER_RADII["Round"].card, CORNER_RADII["Round"].control) == (18, 12)

    for scale, expected in {
        "S": (12, 11, 10, 11),
        "M": (13, 12, 11, 12),
        "L": (15, 14, 13, 13),
    }.items():
        fonts = FONT_SIZE_SCALES[scale]
        assert (fonts.body, fonts.caption, fonts.badge, fonts.mono) == expected
    assert FONT_SIZE_SCALES["M"].thai_line_height_extra == 2


def test_make_theme_resolves_mode_density_metrics_and_preset() -> None:
    dark = make_theme(Settings())
    assert dark.mode == "dark"
    assert dark.color("bg") == PRESETS["Obsidian"].bg[1]
    assert (dark.outer, dark.inner, dark.spacing) == (4, 6, 8)
    assert dark.metrics.window_width == 1040
    assert dark.metrics.window_height == 700
    assert dark.metrics.min_width == 880
    assert dark.metrics.min_height == 600
    assert dark.metrics.toolbar_height == 44
    assert dark.metrics.inspector_width == 300
    assert dark.metrics.console_collapsed_height == 36
    assert dark.metrics.console_expanded_height == 180
    assert dark.metrics.icon_button_size == 26
    assert dark.metrics.primary_height == 36
    assert (dark.radii.card, dark.radii.control) == (12, 8)

    light = make_theme(Settings(appearance="light"))
    assert light.mode == "light"
    assert light.color("bg") == PRESETS["Obsidian"].bg[0]

    system = make_theme(Settings(appearance="system"))
    assert system.mode == "dark"

    comfortable = make_theme(Settings(layout_density="Comfortable"))
    assert (comfortable.outer, comfortable.inner, comfortable.spacing) == (6, 10, 12)

    accent = make_theme(Settings(custom_accent="#FF00FF"))
    assert accent.color("accent") == "#ff00ff"
    assert accent.card_radius == accent.radii.card
    assert accent.control_radius == accent.radii.control


def test_build_qss_uses_theme_values_and_variant_switches() -> None:
    theme = make_theme(Settings())
    qss = build_qss(theme)

    for token in (
        "bg",
        "surface",
        "surface_raised",
        "toolbar_bg",
        "inspector_bg",
        "console_bg",
        "accent",
        "border_focus",
    ):
        assert theme.color(token) in qss, token
    assert f"2px solid {theme.color('border_focus')}" in qss

    for selector in (
        "QMainWindow",
        "QWidget#Root",
        "QWidget#Toolbar",
        "QWidget#Inspector",
        "QWidget#Console",
        "QFrame#Card",
        "QFrame#Hairline",
        'QLabel[role="title"]',
        'QLabel[role="caption"]',
        'QLabel[role="muted"]',
        'QLabel[role="badge"]',
        'QLabel[role="cardCaption"]',
        'QPushButton[variant="primary"]',
        'QPushButton[variant="secondary"]',
        'QPushButton[variant="ghost"]',
        'QPushButton[variant="icon"]',
        "QLineEdit",
        "QComboBox",
        "QComboBox::drop-down",
        "QSpinBox",
        "QPlainTextEdit#ConsoleLog",
        "QProgressBar",
        "QProgressBar::chunk",
        "QScrollBar",
        "QCheckBox",
        "QRadioButton",
        "QMenu",
        "QDialog",
        "QToolTip",
        "QListWidget#QueueList",
    ):
        assert selector in qss, selector

    assert build_qss(make_theme(Settings(layout_density="Comfortable"))) != qss
    assert build_qss(make_theme(Settings(radius_style="Sharp"))) != qss
    assert build_qss(make_theme(Settings(font_size="L"))) != qss
    assert build_qss(make_theme(Settings(theme_preset="Crimson Gamer"))) != qss


def test_build_palette_has_core_and_disabled_roles() -> None:
    theme = make_theme(Settings(theme_preset="Crimson Gamer"))
    palette = build_palette(theme)

    assert palette.color(QPalette.ColorRole.Window).name().lower() == theme.color("bg")
    assert palette.color(QPalette.ColorRole.Base).name().lower() == theme.color("surface")
    assert palette.color(QPalette.ColorRole.Highlight).name().lower() == theme.color("accent")
    disabled = QPalette.ColorGroup.Disabled
    assert palette.color(disabled, QPalette.ColorRole.Text).name().lower() == theme.color("muted")


def test_theme_manager_rebuilds_and_notifies() -> None:
    manager = ThemeManager(Settings())
    seen = []
    manager.subscribe(seen.append)
    manager.apply(Settings(theme_preset="Graphite", layout_density="Comfortable"))

    assert manager.theme.tokens.name == "Graphite"
    assert manager.theme.outer == 6
    assert seen and seen[-1] is manager.theme


def test_settings_round_trip_keeps_layout_density(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(layout_density="Comfortable").save(path)
    assert Settings.load(path).layout_density == "Comfortable"

    path.write_text(json.dumps({"theme_preset": "Graphite"}), encoding="utf-8")
    assert Settings.load(path).layout_density == "Compact"

    stale = Settings(layout_density="Cozy")
    stale._clamp()
    assert stale.layout_density == "Compact"


def test_body_text_contrast_meets_wcag_aa() -> None:
    muted_report: list[str] = []
    for name, tokens in PRESETS.items():
        for index, mode in enumerate(("light", "dark")):
            for foreground in ("text", "text2"):
                for background in ("bg", "surface"):
                    ratio = _contrast(
                        getattr(tokens, foreground)[index], getattr(tokens, background)[index]
                    )
                    assert ratio >= 4.5, f"{name} {mode} {foreground}/{background} = {ratio:.2f}"
            for background in ("bg", "surface"):
                ratio = _contrast(tokens.muted[index], getattr(tokens, background)[index])
                muted_report.append(f"{name} {mode} muted/{background} = {ratio:.2f}")
                assert ratio >= 4.5, f"{name} {mode} muted/{background} = {ratio:.2f}"


def test_hex_to_colorref() -> None:
    assert hex_to_colorref("#112233") == 0x00332211
    assert hex_to_colorref("#000000") == 0
    assert hex_to_colorref("#FFFFFF") == 0x00FFFFFF
    assert hex_to_colorref("invalid") == 0
