"""Tests for UI icons, layout compacting, strings formatting, and assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from fps_patcher.ui.icons import get_icon
from fps_patcher.ui.log_console import LogConsole
from fps_patcher.ui.strings import t

ASSETS_DIR = Path(__file__).resolve().parent.parent / "src" / "fps_patcher" / "ui" / "assets"


def test_dual_mode_icons_exist_and_specs() -> None:
    expected_icons = [
        "zap",
        "chevron_right",
        "chevron_down",
        "play",
        "more",
        "sun",
        "moon",
        "folder",
        "settings",
        "forensic",
    ]
    for name in expected_icons:
        for mode in ("light", "dark"):
            p = ASSETS_DIR / f"{name}_{mode}.png"
            assert p.is_file(), f"Missing icon asset: {p.name}"
            with Image.open(p) as im:
                assert im.size == (32, 32), f"Icon {p.name} size {im.size} != (32, 32)"
                assert im.mode == "RGBA", f"Icon {p.name} mode {im.mode} != RGBA"
                # Ensure non-empty alpha
                bbox = im.getchannel("A").getbbox()
                assert bbox is not None, f"Icon {p.name} is completely transparent"


def test_get_icon_returns_cached_ctk_image() -> None:
    from fps_patcher.ui.icons import clear_icon_cache
    clear_icon_cache()

    ico1 = get_icon("zap", (16, 16))
    assert ico1 is not None

    # Cache check
    ico2 = get_icon("zap", (16, 16))
    assert ico1 is ico2

    chev_down = get_icon("chevron_down", (12, 12), force_dark=True)
    assert chev_down is not None

    chev_right = get_icon("chevron_right", (12, 12))
    assert chev_right is not None

    play_ico = get_icon("play", (16, 16))
    assert play_ico is not None

    missing = get_icon("non_existent_icon_xyz", (16, 16))
    assert missing is None


def test_start_patch_strings_no_emoji() -> None:
    en_start = t("start_patch", "en")
    assert en_start == "Start Patch"
    assert "⚡" not in en_start

    th_start = t("start_patch", "th")
    assert th_start == "เริ่มแปลงไฟล์"
    assert "⚡" not in th_start


def test_console_line_count_strings() -> None:
    # English: 1 line vs 0/N lines
    assert t("console_line_one", "en", count=1) == "1 line"
    assert t("console_lines", "en", count=0) == "0 lines"
    assert t("console_lines", "en", count=42) == "42 lines"

    # Thai: 1 รายการ vs 0/N รายการ
    assert t("console_line_one", "th", count=1) == "1 รายการ"
    assert t("console_lines", "th", count=0) == "0 รายการ"
    assert t("console_lines", "th", count=42) == "42 รายการ"


def test_log_console_format_line_count() -> None:
    class DummyConsole:
        def __init__(self, lang: str = "en") -> None:
            self._language = lang

        def _lang(self) -> str:
            return self._language

    en_console = DummyConsole("en")
    assert LogConsole._format_line_count(en_console, 0) == "0 lines"  # type: ignore[arg-type]
    assert LogConsole._format_line_count(en_console, 1) == "1 line"  # type: ignore[arg-type]
    assert LogConsole._format_line_count(en_console, 5) == "5 lines"  # type: ignore[arg-type]

    th_console = DummyConsole("th")
    assert LogConsole._format_line_count(th_console, 0) == "0 รายการ"  # type: ignore[arg-type]
    assert LogConsole._format_line_count(th_console, 1) == "1 รายการ"  # type: ignore[arg-type]
    assert LogConsole._format_line_count(th_console, 5) == "5 รายการ"  # type: ignore[arg-type]
