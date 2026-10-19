"""Central design system, color palette, typography, and backdrop styling."""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
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
        border=("#E4E4E7", "#323236"),
        border_hover=("#3B82F6", "#3B82F6"),
        border_focus=("#2563EB", "#3B82F6"),
        text=("#18181B", "#F4F4F5"),
        text2=("#52525B", "#B4B4BD"),
        muted=("#71717A", "#A1A1AA"),
        accent=("#2563EB", "#2563EB"),
        accent_hover=("#3B82F6", "#3B82F6"),
        accent_pressed=("#1D4ED8", "#1D4ED8"),
        accent_light=("#DBEAFE", "#1E2D4A"),
        accent_glow=("#93C5FD", "#2563EB"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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
        border=("#E9D5FF", "#342E42"),
        border_hover=("#8B5CF6", "#A78BFA"),
        border_focus=("#7C3AED", "#C4B5FD"),
        text=("#1E1B4B", "#F4F4F5"),
        text2=("#4C1D95", "#B4B4BD"),
        muted=("#71717A", "#A1A1AA"),
        accent=("#7C3AED", "#8B5CF6"),
        accent_hover=("#6D28D9", "#A78BFA"),
        accent_pressed=("#5B21B6", "#7C3AED"),
        accent_light=("#F3E8FF", "#2E1065"),
        accent_glow=("#DDD6FE", "#3B1E6D"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
        toolbar_bg=("#FCFaff", "#201C28"),
        inspector_bg=("#F3EFFC", "#16131C"),
    ),
    "Emerald Terminal": ThemeTokens(
        name="Emerald Terminal",
        bg=("#F0FDF4", "#161E1B"),
        surface=("#FFFFFF", "#1F2925"),
        surface_raised=("#DCFCE7", "#283530"),
        surface_hover=("#BBF7D0", "#32423C"),
        surface_drop_hover=("#ECFDF5", "#1C2D26"),
        border=("#A7F3D0", "#2E3D37"),
        border_hover=("#10B981", "#34D399"),
        border_focus=("#059669", "#6EE7B7"),
        text=("#064E3B", "#F4F4F5"),
        text2=("#065F46", "#B4B4BD"),
        muted=("#059669", "#A1A1AA"),
        accent=("#059669", "#10B981"),
        accent_hover=("#047857", "#34D399"),
        accent_pressed=("#065F46", "#059669"),
        accent_light=("#D1FAE5", "#064E3B"),
        accent_glow=("#A7F3D0", "#0D3A2C"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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
        border=("#FDA4AF", "#3B2D31"),
        border_hover=("#F43F5E", "#FB7185"),
        border_focus=("#E11D48", "#FDA4AF"),
        text=("#881337", "#F4F4F5"),
        text2=("#9F1239", "#B4B4BD"),
        muted=("#BE123C", "#A1A1AA"),
        accent=("#E11D48", "#F43F5E"),
        accent_hover=("#BE123C", "#FB7185"),
        accent_pressed=("#9F1239", "#E11D48"),
        accent_light=("#FFE4E6", "#4C0519"),
        accent_glow=("#FECDD3", "#45121B"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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
        border=("#E4E4E7", "#323236"),
        border_hover=("#71717A", "#A1A1AA"),
        border_focus=("#52525B", "#E4E4E7"),
        text=("#18181B", "#F4F4F5"),
        text2=("#52525B", "#B4B4BD"),
        muted=("#71717A", "#A1A1AA"),
        accent=("#2563EB", "#3B82F6"),
        accent_hover=("#3B82F6", "#60A5FA"),
        accent_pressed=("#1D4ED8", "#2563EB"),
        accent_light=("#DBEAFE", "#1E2D4A"),
        accent_glow=("#93C5FD", "#2563EB"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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
        border=("#FCD34D", "#3A342A"),
        border_hover=("#F59E0B", "#FBBF24"),
        border_focus=("#D97706", "#FDE68A"),
        text=("#78350F", "#F4F4F5"),
        text2=("#92400E", "#B4B4BD"),
        muted=("#B45309", "#A1A1AA"),
        accent=("#D97706", "#F59E0B"),
        accent_hover=("#B45309", "#FBBF24"),
        accent_pressed=("#92400E", "#D97706"),
        accent_light=("#FEF3C7", "#451A03"),
        accent_glow=("#FDE68A", "#422808"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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
        border=("#E4E4E7", "#323236"),
        border_hover=("#3B82F6", "#3B82F6"),
        border_focus=("#2563EB", "#3B82F6"),
        text=("#18181B", "#F4F4F5"),
        text2=("#52525B", "#B4B4BD"),
        muted=("#71717A", "#A1A1AA"),
        accent=("#2563EB", "#2563EB"),
        accent_hover=("#3B82F6", "#3B82F6"),
        accent_pressed=("#1D4ED8", "#1D4ED8"),
        accent_light=("#DBEAFE", "#1E2D4A"),
        accent_glow=("#93C5FD", "#2563EB"),
        success=("#16A34A", "#22C55E"),
        warn=("#D97706", "#F59E0B"),
        danger=("#DC2626", "#EF4444"),
        console_bg=("#141417", "#141417"),
        console_border=("#27272A", "#27272A"),
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

STATUS_SUCCESS_BG = ("#DCFCE7", "#142E1F")
STATUS_SUCCESS_TEXT = ("#15803D", "#22C55E")
STATUS_SUCCESS_BORDER = ("#86EFAC", "#22C55E")

STATUS_WARNING_BG = ("#FEF3C7", "#2B2111")
STATUS_WARNING_TEXT = ("#92400E", "#FCD34D")
STATUS_WARNING_BORDER = ("#F59E0B", "#92400E")

STATUS_DANGER_BG = ("#FEE2E2", "#2D1619")
STATUS_DANGER_TEXT = ("#DC2626", "#EF4444")
STATUS_DANGER_BORDER = ("#FCA5A5", "#EF4444")

STATUS_EXPERIMENTAL_BG = ("#F3E8FF", "#2E1065")
STATUS_EXPERIMENTAL_TEXT = ("#7E22CE", "#C084FC")
STATUS_EXPERIMENTAL_BORDER = ("#D8B4FE", "#A855F7")

STATUS_MUTED_BG = ("#EAEAEF", "#2E2E33")
STATUS_MUTED_TEXT = ("#71717A", "#A1A1AA")
STATUS_MUTED_BORDER = ("#D4D4D8", "#3F3F46")

CONSOLE_BG = _default.console_bg
CONSOLE_BORDER = _default.console_border
CONSOLE_TEXT = ("#D4D4D8", "#D4D4D8")

CONSOLE_LEVEL_COLORS: dict[str, str] = {
    "INFO": "#D4D4D8",
    "OK": "#22C55E",
    "WARN": "#FBBF24",
    "ERROR": "#EF4444",
    "CMD": "#7DD3FC",
    "DIM": "#71717A",
    "DEBUG": "#71717A",
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

_FONT_FAMILY_UI = (
    "SF Pro Text, -apple-system, sans-serif"
    if sys.platform == "darwin"
    else "Segoe UI Variable, Segoe UI, Leelawadee UI, Noto Sans Thai, sans-serif"
)
_FONT_FAMILY_MONO = "SF Mono, Cascadia Mono, Consolas, Courier New, monospace"


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
        size=_font_scale(14 if bold else 13, size_opt),
        weight="bold" if bold else "normal",
    )


def font_caption(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(12, size_opt), weight="normal")


def font_big_stat(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(22, size_opt), weight="bold")


def font_mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_MONO, size=size)


# ============================================================================
# 6. WINDOW BACKDROP & DARK TINT ENGINE (WINDOWS 10/11)
# ============================================================================

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_TYPE_MICA = 2
BACKDROP_TYPE_ACRYLIC = 3


def enable_dark_title_bar(window: Any) -> None:
    """Enables Windows 10/11 DWM dark title bar via Win32 API."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )


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

    enable_dark_title_bar(window)

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
