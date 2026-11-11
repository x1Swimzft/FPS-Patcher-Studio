"""Qt design tokens, density metrics, fonts and Windows DWM helpers.

Everything Qt-facing here only needs PySide6.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFontDatabase

from ..config import DEFAULT_THEME_PRESET, THEME_PRESETS, Settings

# ============================================================================
# 1. COLOUR TOKENS
# ============================================================================


def _rgb(color: str) -> tuple[int, int, int]:
    clean = color.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _mix(fg: str, bg: str, ratio: float) -> str:
    """Blend ``fg`` over ``bg``; ratio 0 = bg, 1 = fg."""
    fr, fg_g, fb = _rgb(fg)
    br, bg_g, bb = _rgb(bg)
    red = round(fr * ratio + br * (1 - ratio))
    green = round(fg_g * ratio + bg_g * (1 - ratio))
    blue = round(fb * ratio + bb * (1 - ratio))
    return f"#{red:02X}{green:02X}{blue:02X}"


def _readable_on(color: str) -> str:
    """Pick dark or light text for an accent fill by perceived brightness."""
    r, g, b = _rgb(color)
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    return "#111111" if brightness > 120 else "#FFFFFF"


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    bg: tuple[str, str]
    surface: tuple[str, str]
    surface_raised: tuple[str, str]
    surface_hover: tuple[str, str]
    surface_drop_hover: tuple[str, str]
    border: tuple[str, str]
    border_hover: tuple[str, str]
    border_focus: tuple[str, str]
    text: tuple[str, str]
    text2: tuple[str, str]
    muted: tuple[str, str]
    accent: tuple[str, str]
    accent_hover: tuple[str, str]
    accent_pressed: tuple[str, str]
    accent_light: tuple[str, str]
    accent_glow: tuple[str, str]
    success: tuple[str, str]
    warn: tuple[str, str]
    danger: tuple[str, str]
    console_bg: tuple[str, str]
    console_border: tuple[str, str]
    toolbar_bg: tuple[str, str] = ("#FAFAFC", "#222226")
    inspector_bg: tuple[str, str] = ("#EEF0F5", "#18181B")
    accent_dim: tuple[str, str] = ("", "")
    accent_dim_border: tuple[str, str] = ("", "")
    on_accent: tuple[str, str] = ("", "")
    border_control: tuple[str, str] = ("#9A9385", "#6E6A62")

    def __post_init__(self) -> None:
        # Derived once at import so every preset has a muted accent fill and a
        # readable foreground for primary buttons.
        if not all(self.accent_dim):
            object.__setattr__(
                self, "accent_dim", (_mix(self.accent[0], self.bg[0], 0.10),
                                     _mix(self.accent[1], self.bg[1], 0.10))
            )
        if not all(self.accent_dim_border):
            object.__setattr__(
                self, "accent_dim_border", (_mix(self.accent[0], self.bg[0], 0.42),
                                            _mix(self.accent[1], self.bg[1], 0.42))
            )
        if not all(self.on_accent):
            object.__setattr__(
                self,
                "on_accent",
                (_readable_on(self.accent[0]), _readable_on(self.accent[1])),
            )


# Neutral surfaces are shared by every preset so a theme changes the accent,
# not the structure. Every pair is (light, dark).
_LIGHT_BG = "#F5F1F2"
_DARK_BG = "#0A0A0F"


def _preset(
    name: str,
    *,
    accent: tuple[str, str],
    accent_hover: tuple[str, str],
    accent_pressed: tuple[str, str],
    accent_light: tuple[str, str] | None = None,
    accent_dim: tuple[str, str] | None = None,
    accent_dim_border: tuple[str, str] | None = None,
) -> ThemeTokens:
    return ThemeTokens(
        name=name,
        bg=(_LIGHT_BG, _DARK_BG),
        surface=("#FFFFFF", "#111118"),
        surface_raised=("#F7F2F3", "#191923"),
        surface_hover=("#EEE6E8", "#23262B"),
        surface_drop_hover=(
            _mix(accent[0], _LIGHT_BG, 0.12),
            _mix(accent[1], _DARK_BG, 0.12),
        ),
        border=("#E3D8DB", "#242432"),
        border_hover=("#C9BFC2", "#3A3A46"),
        border_focus=accent,
        text=("#1C1417", "#ECEBF2"),
        text2=("#463A3E", "#C9C8D6"),
        muted=("#6D5D62", "#9A99AB"),
        accent=accent,
        accent_hover=accent_hover,
        accent_pressed=accent_pressed,
        accent_light=accent_light
        or (_mix(accent[0], "#111111", 0.55), _mix(accent[1], "#FFFFFF", 0.55)),
        accent_glow=(
            _mix(accent[0], _LIGHT_BG, 0.35),
            _mix(accent[1], _DARK_BG, 0.35),
        ),
        success=("#15803D", "#4ADE80"),
        warn=("#8A5A14", "#D6A45F"),
        danger=("#B91C1C", "#FF8A99"),
        console_bg=("#EFE9EA", "#0A0A0F"),
        console_border=("#E3D8DB", "#242432"),
        toolbar_bg=(_LIGHT_BG, _DARK_BG),
        inspector_bg=("#FAF7F8", "#111118"),
        border_control=("#E3D8DB", "#242432"),
        accent_dim=accent_dim or ("", ""),
        accent_dim_border=accent_dim_border or ("", ""),
    )


PRESETS: dict[str, ThemeTokens] = {
    "Crimson Gamer": _preset(
        "Crimson Gamer",
        accent=("#C8283F", "#C8283F"),
        accent_hover=("#A81F33", "#D93450"),
        accent_pressed=("#8F1A2B", "#B32337"),
        accent_light=("#A81F33", "#FF5A70"),
        accent_dim=("#FBE9EC", "#2A1119"),
        accent_dim_border=("#E7B3BD", "#6B1F30"),
    ),
    "Graphite": _preset(
        "Graphite",
        accent=("#3D637F", "#8FB0C9"),
        accent_hover=("#35536A", "#A3C2D9"),
        accent_pressed=("#2A4558", "#6F92AB"),
    ),
    "Midnight Violet": _preset(
        "Midnight Violet",
        accent=("#5B3E9E", "#B7A0E8"),
        accent_hover=("#4B3285", "#C9B6F2"),
        accent_pressed=("#3C276C", "#9C82CF"),
    ),
    "Emerald Terminal": _preset(
        "Emerald Terminal",
        accent=("#1F6F63", "#6FB3A8"),
        accent_hover=("#185A50", "#8BC9BF"),
        accent_pressed=("#124A42", "#569A90"),
    ),
    "Obsidian": _preset(
        "Obsidian",
        accent=("#7A5A24", "#C2A36B"),
        accent_hover=("#694D1D", "#D2B47C"),
        accent_pressed=("#563E15", "#A98B55"),
    ),
    "Amber Warm": _preset(
        "Amber Warm",
        accent=("#8A5A14", "#D9A441"),
        accent_hover=("#744A10", "#E8B85C"),
        accent_pressed=("#5E3B0C", "#B9872E"),
    ),
    "Light": _preset(
        "Light",
        accent=("#4A4E54", "#B9BDC4"),
        accent_hover=("#3D4147", "#CDD1D8"),
        accent_pressed=("#303338", "#9FA4AC"),
    ),
}

assert set(PRESETS) == set(THEME_PRESETS), "PRESETS must mirror config.THEME_PRESETS"

# ============================================================================
# 2. DENSITY, METRICS, RADII AND TYPE
# ============================================================================


@dataclass(frozen=True)
class Density:
    name: str
    outer: int
    inner: int
    spacing: int


DENSITY_METRICS: dict[str, Density] = {
    "Compact": Density("Compact", outer=4, inner=6, spacing=8),
    "Comfortable": Density("Comfortable", outer=6, inner=10, spacing=12),
}


@dataclass(frozen=True)
class Metrics:
    window_width: int = 1040
    window_height: int = 700
    min_width: int = 880
    min_height: int = 600
    toolbar_height: int = 48
    inspector_width: int = 300
    console_collapsed_height: int = 32
    console_expanded_height: int = 180
    button_height: int = 30
    icon_button_size: int = 28
    segmented_height: int = 32
    entry_height: int = 30
    combo_height: int = 30
    primary_height: int = 44
    secondary_height: int = 30
    indicator_size: int = 16
    scrollbar_thickness: int = 8
    progress_height: int = 4

@dataclass(frozen=True)
class Radii:
    card: int
    control: int


CORNER_RADII: dict[str, Radii] = {
    "Sharp": Radii(card=4, control=4),
    "Normal": Radii(card=14, control=10),
    "Round": Radii(card=18, control=12),
}

# Chips are technical tags now; no 999px pills anywhere in the shell.
RADIUS_PILL = 4


@dataclass(frozen=True)
class FontSizes:
    body: int
    caption: int
    badge: int
    mono: int
    thai_line_height_extra: int = 2


FONT_SIZE_SCALES: dict[str, FontSizes] = {
    "S": FontSizes(body=12, caption=12, badge=11, mono=11),
    "M": FontSizes(body=13, caption=12, badge=11, mono=12),
    "L": FontSizes(body=15, caption=13, badge=12, mono=13),
}

UI_FONT_FAMILIES = (
    "Inter",
    "Segoe UI Variable",
    "Segoe UI",
    "Noto Sans Thai",
    "Leelawadee UI",
)
MONO_FONT_FAMILIES = ("Cascadia Mono", "Consolas")

_FONTS_DIR = Path(__file__).resolve().parent.parent / "ui" / "assets" / "fonts"
_LOADED_FAMILIES: list[str] = []


def load_qt_fonts() -> list[str]:
    """Load bundled Inter TTFs into Qt and return the registered families."""
    if _LOADED_FAMILIES:
        return list(_LOADED_FAMILIES)
    if not _FONTS_DIR.is_dir():
        return []
    for font_path in sorted(_FONTS_DIR.glob("*.ttf")):
        with contextlib.suppress(Exception):
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                _LOADED_FAMILIES.extend(QFontDatabase.applicationFontFamilies(font_id))
    return list(_LOADED_FAMILIES)


# ============================================================================
# 3. RESOLVED THEME
# ============================================================================


@dataclass(frozen=True)
class Theme:
    tokens: ThemeTokens
    mode: str
    density: Density
    metrics: Metrics
    radii: Radii
    fonts: FontSizes
    appearance: str = "dark"
    language: str = "en"
    reduce_motion: bool = False
    window_alpha: float = 1.0

    def color(self, name: str) -> str:
        """Resolve a token name for the current light/dark mode."""
        pair: tuple[str, str] = getattr(self.tokens, name)
        return pair[0] if self.mode == "light" else pair[1]

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"

    @property
    def card_radius(self) -> int:
        """Alias used by the shared card widgets."""
        return self.radii.card

    @property
    def control_radius(self) -> int:
        """Alias used by the shared control widgets."""
        return self.radii.control

    def __getattr__(self, name: str) -> Any:
        """Expose density/metrics/radii/type fields directly (e.g. ``outer``)."""
        if name.startswith("__"):
            raise AttributeError(name)
        for source in (self.density, self.metrics, self.radii, self.fonts):
            if hasattr(source, name):
                return getattr(source, name)
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")


def _custom_accent(raw: str) -> str | None:
    accent = (raw or "").strip()
    if len(accent) != 7 or not accent.startswith("#"):
        return None
    try:
        int(accent[1:], 16)
    except ValueError:
        return None
    return accent.lower()


def make_theme(settings: Settings) -> Theme:
    """Resolve presets and layout switches from persisted settings."""
    tokens = PRESETS.get(settings.theme_preset, PRESETS[DEFAULT_THEME_PRESET])
    accent = _custom_accent(getattr(settings, "custom_accent", ""))
    if accent:
        light_text = _mix(accent, "#111111", 0.60)
        dark_text = _mix(accent, "#FFFFFF", 0.60)
        tokens = replace(
            tokens,
            accent=(accent, accent),
            accent_hover=(accent, accent),
            accent_pressed=(accent, accent),
            accent_light=(light_text, dark_text),
            accent_dim=("", ""),
            accent_dim_border=("", ""),
            on_accent=("", ""),
        )
    mode = "light" if settings.appearance == "light" else "dark"
    density = DENSITY_METRICS.get(
        getattr(settings, "layout_density", "Compact"), DENSITY_METRICS["Compact"]
    )
    radii = CORNER_RADII.get(settings.radius_style, CORNER_RADII["Normal"])
    fonts = FONT_SIZE_SCALES.get(settings.font_size, FONT_SIZE_SCALES["M"])
    return Theme(
        tokens=tokens,
        mode=mode,
        density=density,
        metrics=Metrics(),
        radii=radii,
        fonts=fonts,
        appearance=settings.appearance,
        language=settings.language,
        reduce_motion=bool(settings.reduce_motion),
        window_alpha=float(settings.window_alpha),
    )


class ThemeManager(QObject):
    """Owns the active Theme and notifies widgets when settings change."""

    changed = Signal(object)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme = make_theme(settings)

    @property
    def theme(self) -> Theme:
        return self._theme

    def apply(self, settings: Settings) -> Theme:
        self._settings = settings
        theme = make_theme(settings)
        if theme == self._theme:
            return theme
        self._theme = theme
        self.changed.emit(theme)
        return theme

    def subscribe(self, callback: Callable[[Theme], None]) -> None:
        self.changed.connect(callback)


# ============================================================================
# 4. WINDOWS TITLE BAR AND BACKDROP
# ============================================================================

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK = 19
DWMWA_CAPTION_COLOR = 35
DWMWA_SYSTEMBACKDROP_TYPE = 38

_BACKDROP_TYPES = {"Solid": 1, "Mica": 2, "Acrylic": 3, "Mica Alt": 4, "Aero": 3}


def hex_to_colorref(hex_color: str) -> int:
    """Convert ``#RRGGBB`` to Win32 COLORREF (0x00BBGGRR)."""
    clean = hex_color.lstrip("#")
    if len(clean) != 6:
        return 0
    try:
        r, g, b = _rgb(clean)
    except ValueError:
        return 0
    return (b << 16) | (g << 8) | r


def _resolve_hwnd(hwnd_or_widget: int | Any) -> int:
    if isinstance(hwnd_or_widget, int):
        return hwnd_or_widget
    win_id = getattr(hwnd_or_widget, "winId", None)
    if callable(win_id):
        with contextlib.suppress(Exception):
            return int(win_id())
    return 0


def _windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def update_title_bar_theme(
    hwnd: int | Any, is_dark: bool, bg_color: str | None = None
) -> bool:
    """Paint the native title bar dark/light with the toolbar colour. Never raises."""
    if sys.platform != "win32":
        return False
    try:
        handle = _resolve_hwnd(hwnd)
        if not handle:
            return False
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if is_dark else 0)
        result = dwm.DwmSetWindowAttribute(
            handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
        if result != 0:
            result = dwm.DwmSetWindowAttribute(
                handle,
                DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        if bg_color:
            color = ctypes.c_int(hex_to_colorref(bg_color))
            caption = dwm.DwmSetWindowAttribute(
                handle, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color)
            )
            result = result or caption
        return int(result) == 0
    except Exception:
        return False


def apply_backdrop(
    hwnd_or_widget: int | Any, settings: Settings, theme: Theme
) -> bool:
    """Apply Mica/Acrylic on Windows 11 22621+; False means caller uses solid."""
    if _windows_build() < 22621 or not getattr(settings, "glass", True):
        return False
    if getattr(settings, "glass_mode", "Solid") == "Solid":
        return False
    try:
        handle = _resolve_hwnd(hwnd_or_widget)
        if not handle:
            return False
        backdrop = _BACKDROP_TYPES.get(settings.glass_mode, 1)
        value = ctypes.c_int(backdrop)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(value), ctypes.sizeof(value)
        )
        update_title_bar_theme(handle, theme.is_dark, theme.color("toolbar_bg"))
        return int(result) == 0
    except Exception:
        return False
