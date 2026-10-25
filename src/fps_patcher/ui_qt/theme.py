"""Qt design tokens, density metrics, fonts and Windows DWM helpers.

This module deliberately does not import the legacy ``ui.theme`` module: that
one pulls in customtkinter. Everything Qt-facing here only needs PySide6.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFontDatabase

from ..config import THEME_PRESETS, Settings

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

    def __post_init__(self) -> None:
        # Derived once at import so every preset has a muted accent fill and a
        # readable foreground for primary buttons.
        if not all(self.accent_dim):
            object.__setattr__(
                self, "accent_dim", (_mix(self.accent[0], self.bg[0], 0.14),
                                     _mix(self.accent[1], self.bg[1], 0.14))
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


PRESETS: dict[str, ThemeTokens] = {
    "Obsidian": ThemeTokens(
        name="Obsidian",
        bg=("#F6F6F8", "#1C1C1F"),
        surface=("#FFFFFF", "#252529"),
        surface_raised=("#EAEAEF", "#2E2E33"),
        surface_hover=("#DFDFE6", "#38383E"),
        surface_drop_hover=("#EFF6FF", "#1E2638"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#007AFF", "#0A84FF"),
        border_focus=("#007AFF", "#0A84FF"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#007AFF", "#0A84FF"),
        accent_hover=("#0062CC", "#409CFF"),
        accent_pressed=("#004FB0", "#0071E3"),
        accent_light=("#E5F2FF", "#142D4D"),
        accent_glow=("#B3D7FF", "#0A84FF"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FAFAFC", "#222226"),
        inspector_bg=("#EEF0F5", "#18181B"),
    ),
    "Midnight Violet": ThemeTokens(
        name="Midnight Violet",
        bg=("#FAF8FF", "#1A1721"),
        surface=("#FFFFFF", "#231F2C"),
        surface_raised=("#F3E8FF", "#2D2738"),
        surface_hover=("#EDE9FE", "#373045"),
        surface_drop_hover=("#F3E8FF", "#261E38"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#8B5CF6", "#A78BFA"),
        border_focus=("#7C3AED", "#C4B5FD"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#7C3AED", "#8B5CF6"),
        accent_hover=("#6D28D9", "#A78BFA"),
        accent_pressed=("#5B21B6", "#7C3AED"),
        accent_light=("#F3E8FF", "#2E1065"),
        accent_glow=("#DDD6FE", "#3B1E6D"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FCFAFF", "#201C28"),
        inspector_bg=("#F3EFFC", "#16131C"),
    ),
    "Emerald Terminal": ThemeTokens(
        name="Emerald Terminal",
        bg=("#F0FDF4", "#161E1B"),
        surface=("#FFFFFF", "#1F2925"),
        surface_raised=("#DCFCE7", "#283530"),
        surface_hover=("#BBF7D0", "#32423C"),
        surface_drop_hover=("#ECFDF5", "#1C2D26"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#10B981", "#34D399"),
        border_focus=("#059669", "#6EE7B7"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#059669", "#10B981"),
        accent_hover=("#047857", "#34D399"),
        accent_pressed=("#065F46", "#059669"),
        accent_light=("#D1FAE5", "#064E3B"),
        accent_glow=("#A7F3D0", "#0D3A2C"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#F7FEF9", "#1B2420"),
        inspector_bg=("#E9F9EF", "#131A17"),
    ),
    "Crimson Gamer": ThemeTokens(
        name="Crimson Gamer",
        bg=("#fdf6f7", "#0a0a0f"),
        surface=("#ffffff", "#111118"),
        surface_raised=("#fbeaec", "#191923"),
        surface_hover=("#f6dadd", "#232334"),
        surface_drop_hover=("#fdf0f2", "#160f1a"),
        border=("#e6c9cd", "#242432"),
        border_hover=("#c8283f", "#ff5a70"),
        border_focus=("#c8283f", "#ff5a70"),
        text=("#1d1d1f", "#ecebf2"),
        text2=("#6e6e73", "#c9c8d6"),
        muted=("#a99a9d", "#9a99ab"),
        accent=("#c8283f", "#c8283f"),
        accent_hover=("#a91f33", "#d93049"),
        accent_pressed=("#8b1a2a", "#a91f33"),
        accent_light=("#fbe4e8", "#ff5a70"),
        accent_glow=("#e8a6b0", "#ff5a70"),
        accent_dim=("#fbe4e8", "#2a1119"),
        accent_dim_border=("#e8a6b0", "#6b1f30"),
        success=("#34c759", "#30d158"),
        warn=("#ff9500", "#ff9f0a"),
        danger=("#ff3b30", "#ff453a"),
        console_bg=("#141417", "#07070b"),
        console_border=("#2c2c2e", "#2c2c2e"),
        toolbar_bg=("#fbf3f4", "#0d0d13"),
        inspector_bg=("#faecee", "#0d0d13"),
    ),
    "Graphite": ThemeTokens(
        name="Graphite",
        bg=("#F6F6F8", "#1C1C1F"),
        surface=("#FFFFFF", "#252529"),
        surface_raised=("#E4E4E7", "#2E2E33"),
        surface_hover=("#D4D4D8", "#38383E"),
        surface_drop_hover=("#F4F4F5", "#252529"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#6E6E73", "#8E8E93"),
        border_focus=("#1D1D1F", "#D9D9DC"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#007AFF", "#0A84FF"),
        accent_hover=("#0062CC", "#409CFF"),
        accent_pressed=("#004FB0", "#0071E3"),
        accent_light=("#E5F2FF", "#142D4D"),
        accent_glow=("#B3D7FF", "#0A84FF"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FAFAFC", "#222226"),
        inspector_bg=("#EEF0F5", "#18181B"),
    ),
    "Amber Warm": ThemeTokens(
        name="Amber Warm",
        bg=("#FFFBEB", "#1E1B16"),
        surface=("#FFFFFF", "#28241D"),
        surface_raised=("#FEF3C7", "#332E25"),
        surface_hover=("#FDE68A", "#3E382D"),
        surface_drop_hover=("#FFFBEB", "#2B251B"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#FF9500", "#FF9F0A"),
        border_focus=("#FF9500", "#FF9F0A"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#FF9500", "#FF9F0A"),
        accent_hover=("#E08500", "#FFB340"),
        accent_pressed=("#C67600", "#FF9500"),
        accent_light=("#FEF3C7", "#451A03"),
        accent_glow=("#FDE68A", "#422808"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FFFDF5", "#24201A"),
        inspector_bg=("#FAF3DC", "#191612"),
    ),
    "Light": ThemeTokens(
        name="Light",
        bg=("#F6F6F8", "#1C1C1F"),
        surface=("#FFFFFF", "#252529"),
        surface_raised=("#EAEAEF", "#2E2E33"),
        surface_hover=("#DFDFE6", "#38383E"),
        surface_drop_hover=("#EFF6FF", "#1E2638"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#007AFF", "#0A84FF"),
        border_focus=("#007AFF", "#0A84FF"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#007AFF", "#0A84FF"),
        accent_hover=("#0062CC", "#409CFF"),
        accent_pressed=("#004FB0", "#0071E3"),
        accent_light=("#E5F2FF", "#142D4D"),
        accent_glow=("#B3D7FF", "#0A84FF"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FAFAFC", "#222226"),
        inspector_bg=("#EEF0F5", "#18181B"),
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
    toolbar_height: int = 44
    inspector_width: int = 300
    console_collapsed_height: int = 36
    console_expanded_height: int = 180
    button_height: int = 26
    icon_button_size: int = 26
    segmented_height: int = 30
    entry_height: int = 28
    combo_height: int = 28
    primary_height: int = 36
    secondary_height: int = 28
    indicator_size: int = 16
    scrollbar_thickness: int = 10
    progress_height: int = 6


@dataclass(frozen=True)
class Radii:
    card: int
    control: int


CORNER_RADII: dict[str, Radii] = {
    "Sharp": Radii(card=4, control=4),
    "Normal": Radii(card=12, control=8),
    "Round": Radii(card=18, control=12),
}

RADIUS_PILL = 999


@dataclass(frozen=True)
class FontSizes:
    body: int
    caption: int
    badge: int
    mono: int
    thai_line_height_extra: int = 2


FONT_SIZE_SCALES: dict[str, FontSizes] = {
    "S": FontSizes(body=12, caption=11, badge=10, mono=11),
    "M": FontSizes(body=13, caption=12, badge=11, mono=12),
    "L": FontSizes(body=15, caption=14, badge=13, mono=13),
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

    def color(self, name: str) -> str:
        """Resolve a token name for the current light/dark mode."""
        pair: tuple[str, str] = getattr(self.tokens, name)
        return pair[0] if self.mode == "light" else pair[1]

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"

    def __getattr__(self, name: str) -> Any:
        """Expose density/metrics/radii/type fields directly (e.g. ``outer``)."""
        if name.startswith("__"):
            raise AttributeError(name)
        for source in (self.density, self.metrics, self.radii, self.fonts):
            if hasattr(source, name):
                return getattr(source, name)
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")


def make_theme(settings: Settings) -> Theme:
    """Resolve presets and layout switches from persisted settings."""
    tokens = PRESETS.get(settings.theme_preset, PRESETS["Obsidian"])
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
        self._theme = make_theme(settings)
        self.changed.emit(self._theme)
        return self._theme

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
        return result == 0
    except Exception:
        return False


def apply_backdrop(
    hwnd_or_widget: int | Any, settings: Settings, theme: Theme
) -> bool:
    """Apply Mica/Acrylic on Windows 11 22621+; False means caller uses solid."""
    if _windows_build() < 22621:
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
        return result == 0
    except Exception:
        return False
