"""Tests for Inter Font Loader, Apple HIG Semantic Colors, Typography, and DWM Title Bar."""

import sys
import tkinter as tk
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fps_patcher.ui.theme import (
    _FONT_FAMILY_MONO,
    _FONT_FAMILY_UI,
    ACCENT,
    BORDER_HAIRLINE,
    DWMWA_CAPTION_COLOR,
    DWMWA_USE_IMMERSIVE_DARK_MODE,
    DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK,
    PRESETS,
    STATUS_DANGER_TEXT,
    STATUS_SUCCESS_TEXT,
    STATUS_WARNING_TEXT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    _hex_to_colorref,
    font_badge,
    font_body,
    font_caption,
    font_mono,
    init_theme,
    load_bundled_fonts,
    update_title_bar_theme,
)


@pytest.fixture(scope="module")
def tk_root() -> Generator[tk.Tk | None, None, None]:
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        root.destroy()
    except Exception:
        yield None


def test_font_files_exist_and_loader() -> None:
    fonts_dir = Path("src/fps_patcher/ui/assets/fonts")
    assert fonts_dir.is_dir()
    for name in ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"]:
        assert (fonts_dir / name).is_file()

    # Call font loader and init_theme
    load_bundled_fonts()
    init_theme()


def test_font_family_priority() -> None:
    if sys.platform == "darwin":
        assert _FONT_FAMILY_UI == "Inter, SF Pro Text, -apple-system, sans-serif"
    else:
        expected = (
            "Inter, Noto Sans Thai, Segoe UI Variable, "
            "Segoe UI, Leelawadee UI, sans-serif"
        )
        assert expected == _FONT_FAMILY_UI
    assert "SF Mono" in _FONT_FAMILY_MONO
    assert "Cascadia Mono" in _FONT_FAMILY_MONO
    assert "Consolas" in _FONT_FAMILY_MONO


def test_font_sizes_and_badge(tk_root: tk.Tk | None) -> None:
    if tk_root is None:
        pytest.skip("Tkinter not available in headless environment")

    # Body base size 13px (both bold and normal)
    body_normal = font_body(bold=False, size_opt="M")
    body_bold = font_body(bold=True, size_opt="M")
    assert body_normal.cget("size") == 13
    assert body_bold.cget("size") == 13
    assert body_normal.cget("weight") == "normal"
    assert body_bold.cget("weight") == "bold"

    # Caption base size 12px
    caption = font_caption(size_opt="M")
    assert caption.cget("size") == 12

    # Badge base size 11px, weight="bold"
    badge = font_badge(size_opt="M")
    assert badge.cget("size") == 11
    assert badge.cget("weight") == "bold"

    # Scaled sizes
    assert font_badge(size_opt="S").cget("size") == 10
    assert font_badge(size_opt="L").cget("size") == 13
    assert font_body(size_opt="S").cget("size") == 12
    assert font_body(size_opt="L").cget("size") == 15

    # Mono font
    mono = font_mono(12)
    assert mono.cget("size") == 12


def test_apple_hig_semantic_constants() -> None:
    # Primary, secondary, muted text
    assert TEXT_PRIMARY == ("#1D1D1F", "#D9D9DC")
    assert TEXT_SECONDARY == ("#6E6E73", "#8E8E93")
    assert TEXT_MUTED == ("#AEAEB2", "#545458")

    # Accent (System Blue)
    assert ACCENT == ("#007AFF", "#0A84FF")

    # Hairline border
    assert BORDER_HAIRLINE == ("#D2D2D7", "#2C2C2E")

    # Status colors
    assert STATUS_SUCCESS_TEXT == ("#34C759", "#30D158")
    assert STATUS_WARNING_TEXT == ("#FF9500", "#FF9F0A")
    assert STATUS_DANGER_TEXT == ("#FF3B30", "#FF453A")


def test_presets_apple_hig_colors_and_opaque_surfaces() -> None:
    for name, tokens in PRESETS.items():
        # Text colors
        assert tokens.text == ("#1D1D1F", "#D9D9DC"), f"{name} text mismatch"
        assert tokens.text2 == ("#6E6E73", "#8E8E93"), f"{name} text2 mismatch"
        assert tokens.muted == ("#AEAEB2", "#545458"), f"{name} muted mismatch"

        # Semantic status colors
        assert tokens.success == ("#34C759", "#30D158"), f"{name} success mismatch"
        assert tokens.warn == ("#FF9500", "#FF9F0A"), f"{name} warn mismatch"
        assert tokens.danger == ("#FF3B30", "#FF453A"), f"{name} danger mismatch"

        # Hairline borders
        assert tokens.border == ("#D2D2D7", "#2C2C2E"), f"{name} border mismatch"

        # 100% opaque surface checks: 7 chars (#RRGGBB)
        surface_fields = [
            "bg",
            "surface",
            "surface_raised",
            "surface_hover",
            "console_bg",
            "toolbar_bg",
            "inspector_bg",
        ]
        for field_name in surface_fields:
            color_pair = getattr(tokens, field_name)
            for c in color_pair:
                assert c.startswith("#")
                assert len(c) == 7, (
                    f"{name}.{field_name} color '{c}' must be 6 hex digits (100% opaque)"
                )


def test_hex_to_colorref() -> None:
    # COLORREF format is 0x00BBGGRR
    # #112233 -> R=0x11, G=0x22, B=0x33 -> 0x00332211
    assert _hex_to_colorref("#112233") == 0x00332211
    assert _hex_to_colorref("#000000") == 0
    assert _hex_to_colorref("#FFFFFF") == 0x00FFFFFF
    assert _hex_to_colorref("invalid") == 0


def test_update_title_bar_theme_calls_dwm() -> None:
    mock_window = MagicMock()
    mock_window.winfo_id.return_value = 12345

    with patch("ctypes.windll.user32.GetParent", return_value=12345), \
         patch("ctypes.windll.dwmapi.DwmSetWindowAttribute", return_value=0) as mock_dwm:
        # Dark mode with caption color
        update_title_bar_theme(mock_window, is_dark=True, bg_color="#222226")
        assert mock_dwm.call_count >= 1
        # Check first call used attribute 20
        first_call = mock_dwm.call_args_list[0]
        assert first_call[0][1] == DWMWA_USE_IMMERSIVE_DARK_MODE
        # Check second call used attribute 35 (CAPTION_COLOR)
        second_call = mock_dwm.call_args_list[1]
        assert second_call[0][1] == DWMWA_CAPTION_COLOR

        # Test fallback attribute 19 when 20 returns error
        mock_dwm.reset_mock()
        mock_dwm.side_effect = [-1, 0, 0]  # First call fails, second succeeds
        update_title_bar_theme(mock_window, is_dark=False, bg_color="#FAFAFC")
        fallback_call = mock_dwm.call_args_list[1]
        assert fallback_call[0][1] == DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK


def test_main_window_has_update_title_bar_theme() -> None:
    from fps_patcher.ui.main_window import MainWindow
    from fps_patcher.ui.main_window import update_title_bar_theme as mw_update_title_bar_theme

    assert callable(mw_update_title_bar_theme)
    assert hasattr(MainWindow, "_refresh_theme")
    assert hasattr(MainWindow, "update_title_bar_theme")
