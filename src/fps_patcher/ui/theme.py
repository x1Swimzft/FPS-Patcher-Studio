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


PRESETS: dict[str, ThemeTokens] = {
    "Obsidian": ThemeTokens(
        name="Obsidian",
        bg=("#F8FAFC", "#05070B"),
        surface=("#FFFFFF", "#0B0F16"),
        surface_raised=("#F1F5F9", "#121823"),
        surface_hover=("#E2E8F0", "#18212E"),
        surface_drop_hover=("#EFF6FF", "#0E1522"),
        border=("#E2E8F0", "#1C2432"),
        border_hover=("#3B82F6", "#3B82F6"),
        border_focus=("#2563EB", "#60A5FA"),
        text=("#0F172A", "#F1F5F9"),
        text2=("#475569", "#A8B3C5"),
        muted=("#64748B", "#8896AB"),
        accent=("#2563EB", "#3B82F6"),
        accent_hover=("#1D4ED8", "#60A5FA"),
        accent_pressed=("#1E40AF", "#2563EB"),
        accent_light=("#DBEAFE", "#1E293B"),
        accent_glow=("#BFDBFE", "#1D3A6B"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#F8FAFC", "#040508"),
        console_border=("#E2E8F0", "#151B26"),
    ),
    "Midnight Violet": ThemeTokens(
        name="Midnight Violet",
        bg=("#FAF8FF", "#07050D"),
        surface=("#FFFFFF", "#0E0B18"),
        surface_raised=("#F5F3FF", "#171226"),
        surface_hover=("#EDE9FE", "#211A37"),
        surface_drop_hover=("#F3E8FF", "#161026"),
        border=("#E9D5FF", "#262040"),
        border_hover=("#8B5CF6", "#A78BFA"),
        border_focus=("#7C3AED", "#C4B5FD"),
        text=("#1E1B4B", "#F1F5F9"),
        text2=("#4C1D95", "#A8B3C5"),
        muted=("#8B5CF6", "#6B778A"),
        accent=("#7C3AED", "#8B5CF6"),
        accent_hover=("#6D28D9", "#A78BFA"),
        accent_pressed=("#5B21B6", "#7C3AED"),
        accent_light=("#F3E8FF", "#2E1065"),
        accent_glow=("#DDD6FE", "#3B1E6D"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#FAF8FF", "#050309"),
        console_border=("#E9D5FF", "#1D1730"),
    ),
    "Emerald Terminal": ThemeTokens(
        name="Emerald Terminal",
        bg=("#F0FDF4", "#030806"),
        surface=("#FFFFFF", "#08120E"),
        surface_raised=("#DCFCE7", "#0F1D17"),
        surface_hover=("#BBF7D0", "#172E24"),
        surface_drop_hover=("#ECFDF5", "#0B1A14"),
        border=("#A7F3D0", "#17302A"),
        border_hover=("#10B981", "#34D399"),
        border_focus=("#059669", "#6EE7B7"),
        text=("#064E3B", "#F1F5F9"),
        text2=("#065F46", "#A8B3C5"),
        muted=("#059669", "#6B778A"),
        accent=("#059669", "#10B981"),
        accent_hover=("#047857", "#34D399"),
        accent_pressed=("#065F46", "#059669"),
        accent_light=("#D1FAE5", "#064E3B"),
        accent_glow=("#A7F3D0", "#0D3A2C"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#F0FDF4", "#020504"),
        console_border=("#A7F3D0", "#11241F"),
    ),
    "Crimson Gamer": ThemeTokens(
        name="Crimson Gamer",
        bg=("#FFF1F2", "#090405"),
        surface=("#FFFFFF", "#130A0C"),
        surface_raised=("#FFE4E6", "#1E1013"),
        surface_hover=("#FECDD3", "#2A151B"),
        surface_drop_hover=("#FFF1F2", "#190D10"),
        border=("#FDA4AF", "#34181D"),
        border_hover=("#F43F5E", "#FB7185"),
        border_focus=("#E11D48", "#FDA4AF"),
        text=("#881337", "#F1F5F9"),
        text2=("#9F1239", "#A8B3C5"),
        muted=("#BE123C", "#6B778A"),
        accent=("#E11D48", "#F43F5E"),
        accent_hover=("#BE123C", "#FB7185"),
        accent_pressed=("#9F1239", "#E11D48"),
        accent_light=("#FFE4E6", "#4C0519"),
        accent_glow=("#FECDD3", "#45121B"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#FFF1F2", "#060203"),
        console_border=("#FDA4AF", "#261014"),
    ),
    "Graphite": ThemeTokens(
        name="Graphite",
        bg=("#F4F4F5", "#070707"),
        surface=("#FFFFFF", "#101010"),
        surface_raised=("#E4E4E7", "#181818"),
        surface_hover=("#D4D4D8", "#222222"),
        surface_drop_hover=("#F4F4F5", "#141414"),
        border=("#D4D4D8", "#262626"),
        border_hover=("#71717A", "#A1A1AA"),
        border_focus=("#52525B", "#E4E4E7"),
        text=("#18181B", "#F1F5F9"),
        text2=("#3F3F46", "#A8B3C5"),
        muted=("#71717A", "#6B778A"),
        accent=("#3F3F46", "#E5E7EB"),
        accent_hover=("#27272A", "#FFFFFF"),
        accent_pressed=("#18181B", "#D4D4D8"),
        accent_light=("#E4E4E7", "#27272A"),
        accent_glow=("#D4D4D8", "#333333"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#F4F4F5", "#040404"),
        console_border=("#D4D4D8", "#1E1E1E"),
    ),
    "Amber Warm": ThemeTokens(
        name="Amber Warm",
        bg=("#FFFBEB", "#080604"),
        surface=("#FFFFFF", "#120E08"),
        surface_raised=("#FEF3C7", "#1C150B"),
        surface_hover=("#FDE68A", "#2A1E0F"),
        surface_drop_hover=("#FFFBEB", "#171109"),
        border=("#FCD34D", "#33260F"),
        border_hover=("#F59E0B", "#FBBF24"),
        border_focus=("#D97706", "#FDE68A"),
        text=("#78350F", "#F1F5F9"),
        text2=("#92400E", "#A8B3C5"),
        muted=("#B45309", "#6B778A"),
        accent=("#D97706", "#F59E0B"),
        accent_hover=("#B45309", "#FBBF24"),
        accent_pressed=("#92400E", "#D97706"),
        accent_light=("#FEF3C7", "#451A03"),
        accent_glow=("#FDE68A", "#422808"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#FFFBEB", "#050402"),
        console_border=("#FCD34D", "#261C0B"),
    ),
    "Light": ThemeTokens(
        name="Light",
        bg=("#F8FAFC", "#0F172A"),
        surface=("#FFFFFF", "#1E293B"),
        surface_raised=("#F1F5F9", "#334155"),
        surface_hover=("#E2E8F0", "#475569"),
        surface_drop_hover=("#EFF6FF", "#1E293B"),
        border=("#E2E8F0", "#334155"),
        border_hover=("#3B82F6", "#60A5FA"),
        border_focus=("#2563EB", "#93C5FD"),
        text=("#0F172A", "#F8FAFC"),
        text2=("#475569", "#CBD5E1"),
        muted=("#94A3B8", "#64748B"),
        accent=("#2563EB", "#3B82F6"),
        accent_hover=("#1D4ED8", "#60A5FA"),
        accent_pressed=("#1E40AF", "#2563EB"),
        accent_light=("#DBEAFE", "#1E293B"),
        accent_glow=("#BFDBFE", "#1E3A8A"),
        success=("#15803D", "#34D399"),
        warn=("#B45309", "#FBBF24"),
        danger=("#B91C1C", "#F87171"),
        console_bg=("#F8FAFC", "#0B1120"),
        console_border=("#E2E8F0", "#1E293B"),
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

STATUS_SUCCESS_BG = ("#DCFCE7", "#0F2A22")
STATUS_SUCCESS_TEXT = ("#15803D", "#34D399")
STATUS_SUCCESS_BORDER = ("#86EFAC", "#10B981")

STATUS_WARNING_BG = ("#FEF3C7", "#2D2311")
STATUS_WARNING_TEXT = ("#B45309", "#FBBF24")
STATUS_WARNING_BORDER = ("#FCD34D", "#D97706")

STATUS_DANGER_BG = ("#FEE2E2", "#2A1417")
STATUS_DANGER_TEXT = ("#B91C1C", "#F87171")
STATUS_DANGER_BORDER = ("#FCA5A5", "#EF4444")

STATUS_EXPERIMENTAL_BG = ("#F3E8FF", "#2E1065")
STATUS_EXPERIMENTAL_TEXT = ("#7E22CE", "#C084FC")
STATUS_EXPERIMENTAL_BORDER = ("#D8B4FE", "#A855F7")

STATUS_MUTED_BG = ("#F1F5F9", "#1E293B")
STATUS_MUTED_TEXT = ("#64748B", "#94A3B8")
STATUS_MUTED_BORDER = ("#CBD5E1", "#475569")

CONSOLE_BG = _default.console_bg
CONSOLE_BORDER = _default.console_border
CONSOLE_TEXT = ("#1E293B", "#C9D1D9")

CONSOLE_LEVEL_COLORS: dict[str, str] = {
    "INFO": "#94A3B8",
    "OK": "#34D399",
    "WARN": "#FBBF24",
    "ERROR": "#F87171",
    "DEBUG": "#64748B",
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

_FONT_FAMILY_UI = "Segoe UI Variable, Segoe UI, Leelawadee UI, Noto Sans Thai, sans-serif"
_FONT_FAMILY_MONO = "Cascadia Mono, Consolas, Courier New, monospace"


def _font_scale(base: int, size_opt: str = "M") -> int:
    if size_opt == "S":
        return max(8, base - 1)
    if size_opt == "L":
        return base + 2
    return base


def font_title(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(20, size_opt), weight="bold")


def font_section(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(12, size_opt), weight="bold")


def font_body(bold: bool = False, size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(
        family=_FONT_FAMILY_UI,
        size=_font_scale(13, size_opt),
        weight="bold" if bold else "normal",
    )


def font_caption(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(11, size_opt), weight="normal")


def font_big_stat(size_opt: str = "M") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY_UI, size=_font_scale(26, size_opt), weight="bold")


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
    """Applies acrylic/mica translucent backdrop with dark tint suppression."""
    if os.name != "nt":
        return False

    enable_dark_title_bar(window)

    if not glass or backdrop_mode == "Solid":
        with contextlib.suppress(Exception):
            window.attributes("-alpha", 1.0)
        return True

    applied = False
    style_target = backdrop_mode.lower()  # acrylic, mica, aero

    # 1. Try pywinstyles
    try:
        import pywinstyles

        try:
            pywinstyles.apply_style(window, style_target)
            applied = True
        except Exception:
            for fallback in ("acrylic", "mica", "aero"):
                try:
                    pywinstyles.apply_style(window, fallback)
                    applied = True
                    break
                except Exception:
                    continue
    except ImportError:
        pass

    # 2. Direct ctypes fallback
    if not applied:
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

    # 3. Tint strength calculation: higher tint strength = less alpha bleed
    # Base alpha clamped between 0.85 and 1.0; tint_strength (0-100) pulls alpha toward 1.0
    effective_alpha = max(0.85, min(1.0, float(alpha)))
    if tint_strength >= 80:
        # Strongly suppress background bleed to guarantee high surface contrast (>= 0.98)
        effective_alpha = max(effective_alpha, 0.98)
        effective_alpha = min(1.0, effective_alpha)

    with contextlib.suppress(Exception):
        window.attributes("-alpha", effective_alpha)

    return applied
