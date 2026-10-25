"""Tests for Settings v2, serialization, migrations, clamping, and templates."""

from __future__ import annotations

import json
from pathlib import Path

from fps_patcher.config import (
    Settings,
    render_filename_template,
)
from fps_patcher.ui.strings import t
from fps_patcher.ui_qt.theme import PRESETS


def test_filename_template_rendering() -> None:
    tpl = "{name}_{fps}fps"
    assert render_filename_template(tpl, "my_video", 60) == "my_video_60fps"

    tpl_full = "{name}_patched_{fps}fps_{timescale}ts_{date}"
    rendered = render_filename_template(tpl_full, "clip", 120, timescale=90000, date_str="20261009")
    assert rendered == "clip_patched_120fps_90000ts_20261009"

    # Malformed template should gracefully fallback
    bad_tpl = "{name}_{unknown_field}_{fps}"
    fallback = render_filename_template(bad_tpl, "test", 60)
    assert fallback == "test_60fps"


def test_settings_v2_defaults_and_roundtrip(tmp_path: Path) -> None:
    s = Settings()
    assert s.theme_preset == "Crimson Gamer"
    assert s.tint_strength == 80
    assert s.window_alpha == 1.0
    assert s.qt_v090_migrated is True
    assert s.glass_mode == "Solid"
    assert s.language == "en"

    target_file = tmp_path / "settings.json"
    s.theme_preset = "Midnight Violet"
    s.tint_strength = 95
    s.custom_accent = "#8B5CF6"
    s.language = "th"
    s.save(target_file)

    loaded = Settings.load(target_file)
    assert loaded.theme_preset == "Midnight Violet"
    assert loaded.tint_strength == 95
    assert loaded.custom_accent == "#8B5CF6"
    assert loaded.language == "th"


def test_settings_v2_backward_compatibility_migration(tmp_path: Path) -> None:
    # Emulate older settings.json without v2 fields
    legacy = {
        "ffmpeg_dir": "C:/ffmpeg",
        "output_dir": "D:/out",
        "last_preset": "120 FPS",
        "strategy": "bxd-bypass",
    }
    old_file = tmp_path / "legacy_settings.json"
    old_file.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = Settings.load(old_file)
    assert loaded.ffmpeg_dir == "C:/ffmpeg"
    assert loaded.output_dir == "D:/out"
    assert loaded.last_preset == "120 FPS"
    # v0.9.0 cutover migration: legacy Obsidian + 98% alpha become Crimson + opaque.
    assert loaded.theme_preset == "Crimson Gamer"
    assert loaded.window_alpha == 1.0
    assert loaded.qt_v090_migrated is True
    assert loaded.tint_strength == 80
    assert loaded.glass is True
    assert json.loads(old_file.read_text(encoding="utf-8"))["qt_v090_migrated"] is True


def test_settings_v2_clamping_and_corrupt_recovery(tmp_path: Path) -> None:
    corrupt_data = {
        "tint_strength": 9999,  # Should clamp to 100
        "window_alpha": 0.1,  # Should clamp to 0.85
        "ui_scale": -50,  # Should clamp to 50
        "theme_preset": "NonExistentPreset",  # Fallback to Crimson Gamer
        "glass_mode": "InvalidMode",  # Fallback to Acrylic
        "language": "es",  # Fallback to en
        "qt_v090_migrated": True,  # Exercise clamping, not cutover migration
    }
    corrupt_file = tmp_path / "corrupt_settings.json"
    corrupt_file.write_text(json.dumps(corrupt_data), encoding="utf-8")

    loaded = Settings.load(corrupt_file)
    assert loaded.tint_strength == 100
    assert loaded.window_alpha == 0.85
    assert loaded.ui_scale == 50
    assert loaded.theme_preset == "Crimson Gamer"
    assert loaded.glass_mode == "Acrylic"
    assert loaded.language == "en"

    # Completely unparseable JSON file
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{broken json: 123", encoding="utf-8")
    safe_loaded = Settings.load(broken_file)
    assert safe_loaded.theme_preset == "Crimson Gamer"
    assert safe_loaded.window_alpha == 1.0


def test_concurrent_settings_saves_never_corrupt_the_file(tmp_path: Path) -> None:
    import threading

    target = tmp_path / "settings.json"
    presets = ["Obsidian", "Light", "Graphite", "Midnight Violet"]

    def save_one(preset: str) -> None:
        Settings(theme_preset=preset).save(target)

    threads = [
        threading.Thread(target=save_one, args=(presets[i % len(presets)],))
        for i in range(16)
    ]
    for worker in threads:
        worker.start()
    for worker in threads:
        worker.join(timeout=5)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["theme_preset"] in presets
    assert not list(tmp_path.glob("*.tmp_*"))


def test_localization_strings() -> None:
    assert t("app_title", "en") == "FPS Patcher Studio"
    assert t("app_title", "th") == "FPS Patcher Studio"
    assert t("drop_title", "th") == "ลากไฟล์ MP4 / MOV มาวางที่นี่"
    assert t("settings_btn", "th") == "⚙ ตั้งค่า"
    # Fallback to English if key missing in Thai
    assert t("only_in_en_fallback", "th") == "only_in_en_fallback"

    # FFmpeg auto-download strings
    assert t("ffmpeg_download_btn", "en") == "Download FFmpeg"
    assert t("ffmpeg_download_btn", "th") == "ดาวน์โหลด FFmpeg"
    assert t("ffmpeg_auto_download_btn", "en") == "Auto-Download FFmpeg"
    assert t("ffmpeg_auto_download_btn", "th") == "ดาวน์โหลด FFmpeg อัตโนมัติ"
    assert t("ffmpeg_downloading", "en", percent=50) == "Downloading FFmpeg (50%)..."
    assert t("ffmpeg_downloading", "th", percent=50) == "กำลังดาวน์โหลด FFmpeg (50%)..."
    assert t("ffmpeg_extracting", "en") == "Extracting FFmpeg..."
    assert t("ffmpeg_extracting", "th") == "กำลังแตกไฟล์ FFmpeg..."
    assert t("ffmpeg_installed", "en") == "FFmpeg installed successfully"
    assert t("ffmpeg_installed", "th") == "ติดตั้ง FFmpeg สำเร็จพร้อมใช้งาน"
    assert t("ffmpeg_download_failed", "en") == "FFmpeg download failed"
    assert t("ffmpeg_download_failed", "th") == "ดาวน์โหลด FFmpeg ไม่สำเร็จ"


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = _luminance(hex1)
    l2 = _luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_theme_wcag_contrast() -> None:
    obsidian = PRESETS["Obsidian"]
    dark_bg = obsidian.bg[1]
    dark_text = obsidian.text[1]
    dark_text2 = obsidian.text2[1]

    # WCAG AAA requires >= 7.0:1, AA requires >= 4.5:1
    assert _contrast_ratio(dark_text, dark_bg) >= 7.0  # AAA compliant primary text
    assert _contrast_ratio(dark_text2, dark_bg) >= 4.5  # AA compliant secondary text

