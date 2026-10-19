"""Central design system, color palette, typography, and backdrop styling."""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import customtkinter as ctk

from ..config import Settings

# ============================================================================
# 1. THEME PRESETS DEFINITION
# ============================================================================


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
        bg=("#FFF1F2", "#1F181A"),
        surface=("#FFFFFF", "#292023"),
        surface_raised=("#FFE4E6", "#34282C"),
        surface_hover=("#FECDD3", "#403136"),
        surface_drop_hover=("#FFF1F2", "#2D1E22"),
        border=("#D2D2D7", "#2C2C2E"),
        border_hover=("#F43F5E", "#FB7185"),
        border_focus=("#E11D48", "#FDA4AF"),
        text=("#1D1D1F", "#D9D9DC"),
        text2=("#6E6E73", "#8E8E93"),
        muted=("#AEAEB2", "#545458"),
        accent=("#E11D48", "#F43F5E"),
        accent_hover=("#BE123C", "#FB7185"),
        accent_pressed=("#9F1239", "#E11D48"),
        accent_light=("#FFE4E6", "#4C0519"),
        accent_glow=("#FECDD3", "#45121B"),
        success=("#34C759", "#30D158"),
        warn=("#FF9500", "#FF9F0A"),
        danger=("#FF3B30", "#FF453A"),
        console_bg=("#141417", "#141417"),
        console_border=("#2C2C2E", "#2C2C2E"),
        toolbar_bg=("#FFF7F8", "#241C1E"),
        inspector_bg=("#FCE7E9", "#1A1416"),
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

# ============================================================================
# 2. THEME MANAGER & DYNAMIC OBSERVER
# ============================================================================


class ThemeManager:
    """Manages active preset, custom accent, tinting, and notifies subscribers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tokens = PRESETS.get(settings.theme_preset, PRESETS["Obsidian"])
        self._subscribers: list[Callable[[ThemeTokens], None]] = []

    @property
    def tokens(self) -> ThemeTokens:
        if self.settings.custom_accent and self.settings.custom_accent.startswith("#"):
            acc = self.settings.custom_accent
            return ThemeTokens(
                name=self._tokens.name,
                bg=self._tokens.bg,
                surface=self._tokens.surface,
                surface_raised=self._tokens.surface_raised,
                surface_hover=self._tokens.surface_hover,
                surface_drop_hover=self._tokens.surface_drop_hover,
                border=self._tokens.border,
                border_hover=self._tokens.border_hover,
                border_focus=self._tokens.border_focus,
                text=self._tokens.text,
                text2=self._tokens.text2,
                muted=self._tokens.muted,
                accent=(acc, acc),
                accent_hover=(acc, acc),
                accent_pressed=(acc, acc),
                accent_light=self._tokens.accent_light,
                accent_glow=self._tokens.accent_glow,
                success=self._tokens.success,
                warn=self._tokens.warn,
                danger=self._tokens.danger,
                console_bg=self._tokens.console_bg,
                console_border=self._tokens.console_border,
                toolbar_bg=self._tokens.toolbar_bg,
                inspector_bg=self._tokens.inspector_bg,
            )
        return self._tokens

    def subscribe(self, callback: Callable[[ThemeTokens], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[ThemeTokens], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def apply(self, settings: Settings) -> None:
        self.settings = settings
        preset = PRESETS.get(settings.theme_preset, PRESETS["Obsidian"])
        self._tokens = preset
        ctk.set_appearance_mode(settings.appearance)
        # Notify subscribers
        current = self.tokens
        for sub in list(self._subscribers):
            with contextlib.suppress(Exception):
                sub(current)


_GLOBAL_THEME_MANAGER: ThemeManager | None = None


def get_theme_manager(settings: Settings | None = None) -> ThemeManager:
    global _GLOBAL_THEME_MANAGER
    if _GLOBAL_THEME_MANAGER is None:
        if settings is None:
            settings = Settings()
        _GLOBAL_THEME_MANAGER = ThemeManager(settings)
    elif settings is not None:
        _GLOBAL_THEME_MANAGER.apply(settings)
    return _GLOBAL_THEME_MANAGER


# ============================================================================
# 3. COMPATIBILITY ALIASES (Reflecting Active Tokens)
# ============================================================================

# Module-level defaults map to Obsidian preset
_default = PRESETS["Obsidian"]
WINDOW_BG = _default.bg
SURFACE_CARD = _default.surface
SURFACE_RAISED = _default.surface_raised
SURFACE_HOVER = _default.surface_hover
SURFACE_DROP_HOVER = _default.surface_drop_hover
BORDER_HAIRLINE = _default.border
BORDER_HOVER = _default.border_hover
BORDER_FOCUS = _default.border_focus
TEXT_PRIMARY = _default.text
TEXT_SECONDARY = _default.text2
TEXT_MUTED = _default.muted
ACCENT = _default.accent
ACCENT_HOVER = _default.accent_hover
ACCENT_PRESSED = _default.accent_pressed
ACCENT_LIGHT = _default.accent_light
ACCENT_TOP_BORDER = _default.accent_glow

STATUS_SUCCESS_BG = ("#E8F8ED", "#132E1D")
STATUS_SUCCESS_TEXT = ("#34C759", "#30D158")
STATUS_SUCCESS_BORDER = ("#34C759", "#30D158")

STATUS_WARNING_BG = ("#FFF4E5", "#2B1D0A")
STATUS_WARNING_TEXT = ("#FF9500", "#FF9F0A")
STATUS_WARNING_BORDER = ("#FF9500", "#FF9F0A")

STATUS_DANGER_BG = ("#FFEBEA", "#2D1619")
STATUS_DANGER_TEXT = ("#FF3B30", "#FF453A")
STATUS_DANGER_BORDER = ("#FF3B30", "#FF453A")

STATUS_EXPERIMENTAL_BG = ("#F3E8FF", "#2E1065")
STATUS_EXPERIMENTAL_TEXT = ("#AF52DE", "#BF5AF2")
STATUS_EXPERIMENTAL_BORDER = ("#AF52DE", "#BF5AF2")

STATUS_MUTED_BG = ("#EAEAEF", "#2E2E33")
STATUS_MUTED_TEXT = ("#AEAEB2", "#545458")
STATUS_MUTED_BORDER = ("#D2D2D7", "#2C2C2E")

CONSOLE_BG = _default.console_bg
CONSOLE_BORDER = _default.console_border
CONSOLE_TEXT = ("#D9D9DC", "#D9D9DC")

CONSOLE_LEVEL_COLORS: dict[str, str] = {
    "INFO": "#D9D9DC",
    "OK": "#30D158",
    "WARN": "#FF9F0A",
    "ERROR": "#FF453A",
    "CMD": "#0A84FF",
    "DIM": "#545458",
    "DEBUG": "#545458",
}

# ============================================================================
# 4. DIMENSIONS & RADIUS
# ============================================================================

RADIUS_CARD = 16
RADIUS_CONTROL = 10
RADIUS_PILL = 999

PAD_OUTER = 16
PAD_INNER = 12
PAD_SPACING = 8


def get_corner_radii(style: str = "Normal") -> tuple[int, int]:
    """Returns (card_radius, control_radius) according to style."""
    if style == "Sharp":
        return 4, 4
    if style == "Round":
        return 22, 14
    return 16, 10


# ============================================================================
# 5. TYPOGRAPHY WITH THAI & DYNAMIC SIZING
# ============================================================================

_FONTS_LOADED = False


def load_bundled_fonts() -> None:
    """Load bundled Inter fonts into Windows GDI font table."""
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    _FONTS_LOADED = True
    if sys.platform != "win32":
        return
    fonts_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    if not fonts_dir.is_dir():
        return
    for font_path in fonts_dir.glob("*.ttf"):
        with contextlib.suppress(Exception):
            ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0)


_load_bundled_fonts = load_bundled_fonts


def init_theme() -> None:
    """Initialize theme resources including bundled fonts."""
    load_bundled_fonts()


# Auto-load fonts on module import
with contextlib.suppress(Exception):
    load_bundled_fonts()

_FONT_FAMILY_UI = (
    "Inter, SF Pro Text, -apple-system, sans-serif"
    if sys.platform == "darwin"
    else "Inter, Noto Sans Thai, Segoe UI Variable, Segoe UI, Leelawadee UI, sans-serif"
)
_FONT_FAMILY_MONO = "SF Mono, Cascadia Mono, Consolas, monospace"


def _font_scale(base: int, size_opt: str = "M") -> int:
    if size_opt == "S":
        return max(8, base - 1)
    if size_opt == "L":
        return base + 2
    return base


def font_title(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(14, size_opt), weight="bold")


def font_section(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(13, size_opt), weight="bold")


def font_body(bold: bool = False, size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(
        family=_FONT_FAMILY_UI,
        size=_font_scale(13, size_opt),
        weight="bold" if bold else "normal",
    )


def font_caption(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(12, size_opt), weight="normal")


def font_badge(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(11, size_opt), weight="bold")


def font_big_stat(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(22, size_opt), weight="bold")


def font_mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_MONO, size=size)


# ============================================================================
# 6. WINDOW BACKDROP & TITLE BAR (WINDOWS 10/11 DWM)
# ============================================================================

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK = 19
DWMWA_CAPTION_COLOR = 35
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_TYPE_MICA = 2
BACKDROP_TYPE_ACRYLIC = 3


def _hex_to_colorref(hex_color: str) -> int:
    """Convert hex string (e.g. #222226) to Win32 COLORREF (0x00BBGGRR)."""
    clean = hex_color.lstrip("#")
    if len(clean) == 6:
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
        return (b << 16) | (g << 8) | r
    return 0


def update_title_bar_theme(window: Any, is_dark: bool, bg_color: str | None = None) -> None:
    """Updates Windows 10/11 DWM title bar theme and caption color."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if is_dark else 0)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )

        if bg_color and bg_color.startswith("#"):
            colorref = _hex_to_colorref(bg_color)
            color_val = ctypes.c_int(colorref)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color_val), ctypes.sizeof(color_val)
            )


def enable_dark_title_bar(window: Any) -> None:
    """Enables Windows 10/11 DWM dark title bar via Win32 API."""
    update_title_bar_theme(window, is_dark=True)


def apply_window_backdrop(
    window: Any,
    glass: bool = True,
    alpha: float = 0.96,
    backdrop_mode: str = "Acrylic",
    tint_strength: int = 80,
) -> bool:
    """Applies DWM backdrop while keeping main window surfaces 100% opaque."""
    _ = (alpha, tint_strength)
    if os.name != "nt":
        return False

    is_dark = ctk.get_appearance_mode().lower() == "dark"
    update_title_bar_theme(window, is_dark=is_dark)

    # Always keep whole-window alpha at 1.0 so queue, inspector, and console never bleed through
    with contextlib.suppress(Exception):
        window.attributes("-alpha", 1.0)
        window.wm_attributes("-transparentcolor", "")

    if not glass or backdrop_mode == "Solid":
        return True

    applied = False
    style_target = backdrop_mode.lower()  # acrylic, mica, aero

    # Set DWM system backdrop attribute on frame without color-keying root window bg
    with contextlib.suppress(Exception):
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        code = (
            BACKDROP_TYPE_ACRYLIC if "acrylic" in style_target else BACKDROP_TYPE_MICA
        )
        backdrop = ctypes.c_int(code)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
        if res == 0:
            applied = True

    return applied
