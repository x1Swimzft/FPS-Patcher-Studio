"""Persistent user settings stored as JSON in the per-user app data folder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.strategies import migrate_strategy_name

APP_DIR_NAME = "FPSPatcherStudio"
MAX_BXD_PADDING_BYTES = 512 * 1024 * 1024  # 512 MB ceiling

THEME_PRESETS = [
    "Obsidian",
    "Midnight Violet",
    "Emerald Terminal",
    "Crimson Gamer",
    "Graphite",
    "Amber Warm",
    "Light",
]

BACKDROP_MODES = ["Acrylic", "Mica", "Aero", "Solid"]
FONT_SIZES = ["S", "M", "L"]
RADIUS_STYLES = ["Sharp", "Normal", "Round"]
NOTIFY_MODES = ["none", "sound", "toast"]
LANGUAGES = ["en", "th"]


def app_data_dir() -> Path:
    """Cross-platform per-user application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def render_filename_template(
    template: str,
    original_stem: str,
    fps: int,
    timescale: int = 90000,
    date_str: str | None = None,
) -> str:
    """Format filename template tokens: {name}, {fps}, {timescale}, {date}."""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    template = template or "{name}_{fps}fps"
    try:
        rendered = template.format(
            name=original_stem,
            fps=fps,
            timescale=timescale,
            date=date_str,
        )
    except Exception:
        rendered = f"{original_stem}_{fps}fps"
    # Basic sanitize
    for bad in r'\/:*?"<>|':
        rendered = rendered.replace(bad, "_")
    return rendered.strip() or f"{original_stem}_{fps}fps"


@dataclass
class Settings:
    # Existing fields
    ffmpeg_dir: str = ""
    output_dir: str = ""  # empty = same folder as source
    last_preset: str = "60 FPS"
    custom_timescale: int = 90000
    strategy: str = "bxd-mobile"
    appearance: str = "dark"
    overwrite: bool = False
    auto_rename: bool = True
    v4_strict_lossless: bool = True
    v4_preserve_video: bool = True
    v4_preserve_audio: bool = True
    v4_sync_mvhd: bool = False
    v4_export_report: bool = False
    v4_dry_run: bool = False
    glass: bool = True
    window_alpha: float = 0.98

    # BXD Preset & Diagnostic options
    bxd_padding_bytes: int = 0  # 0 = automatic BXD multiplier size; clamped <= 512 MB
    bxd_max_tail_ms: int = 50  # provisional ceiling (ms, <=200ms) for Bxd Hybrid tail delta shaping
    mask_diagnostic_paths: bool = True

    # V2 Appearance
    theme_preset: str = "Obsidian"
    custom_accent: str = ""
    tint_strength: int = 80
    glass_mode: str = "Solid"
    ui_scale: int = 100
    font_size: str = "M"
    radius_style: str = "Normal"
    reduce_motion: bool = False

    # V2 Output
    filename_template: str = "{name}_{fps}fps"
    open_when_done: bool = False
    preserve_mtime: bool = True

    # V2 Patching
    verify_after: bool = True
    backup_original: bool = True
    stop_on_error: bool = False
    auto_normalize_audio: bool = True
    auto_cap_bitrate: bool = False
    check_updates_on_start: bool = True

    # V2 FFmpeg
    check_ffmpeg_on_start: bool = True
    show_ffmpeg_output: bool = False
    extra_ffmpeg_args: str = ""

    # V2 Console & Logs
    console_font_size: int = 12
    max_log_lines: int = 2000
    log_timestamps: bool = True
    log_autoscroll: bool = True
    log_to_file: bool = True

    # V2 Behavior
    remember_geometry: bool = True
    geometry: str = ""
    always_on_top: bool = False
    confirm_cancel: bool = True
    confirm_overwrite: bool = True
    notify_done: str = "none"
    language: str = "en"

    # Phase 2: watch folder, Explorer verb, lossless color/metadata guard
    watch_folder_enabled: bool = False
    watch_folder: str = ""
    explorer_menu: bool = False
    fix_color_tag: bool = False
    scrub_metadata: bool = False

    # Transient runtime notice (not persisted)
    migrated_strategy_from: str | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or app_data_dir() / "settings.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
        except (OSError, json.JSONDecodeError):
            return cls()

        known = {f.name for f in fields(cls) if f.init}
        filtered: dict[str, Any] = {k: v for k, v in raw.items() if k in known}

        # Safe clamping and validation
        try:
            instance = cls(**filtered)
        except TypeError:
            return cls()

        instance._clamp()
        return instance

    def _clamp(self) -> None:
        """Clamp and validate values safely."""
        new_strat, migrated_from = migrate_strategy_name(str(self.strategy))
        if migrated_from is not None:
            self.migrated_strategy_from = migrated_from
        self.strategy = new_strat

        if self.theme_preset not in THEME_PRESETS:
            self.theme_preset = "Obsidian"
        if self.glass_mode not in BACKDROP_MODES:
            self.glass_mode = "Acrylic"
        if self.font_size not in FONT_SIZES:
            self.font_size = "M"
        if self.radius_style not in RADIUS_STYLES:
            self.radius_style = "Normal"
        if self.notify_done not in NOTIFY_MODES:
            self.notify_done = "none"
        if self.language not in LANGUAGES:
            self.language = "en"

        try:
            self.tint_strength = max(0, min(100, int(self.tint_strength)))
        except (ValueError, TypeError):
            self.tint_strength = 80

        try:
            self.window_alpha = max(0.85, min(1.0, float(self.window_alpha)))
        except (ValueError, TypeError):
            self.window_alpha = 0.96

        try:
            self.ui_scale = max(50, min(200, int(self.ui_scale)))
        except (ValueError, TypeError):
            self.ui_scale = 100

        try:
            self.console_font_size = max(8, min(24, int(self.console_font_size)))
        except (ValueError, TypeError):
            self.console_font_size = 12

        try:
            self.max_log_lines = max(100, min(20000, int(self.max_log_lines)))
        except (ValueError, TypeError):
            self.max_log_lines = 2000

        try:
            self.bxd_padding_bytes = max(0, min(MAX_BXD_PADDING_BYTES, int(self.bxd_padding_bytes)))
        except (ValueError, TypeError):
            self.bxd_padding_bytes = 0

        try:
            self.bxd_max_tail_ms = max(0, min(5000, int(self.bxd_max_tail_ms)))
        except (ValueError, TypeError):
            self.bxd_max_tail_ms = 200

        if not self.filename_template:
            self.filename_template = "{name}_{fps}fps"

        self.watch_folder = str(getattr(self, "watch_folder", "") or "").strip()
        for name in ("watch_folder_enabled", "explorer_menu", "fix_color_tag", "scrub_metadata"):
            raw = getattr(self, name, False)
            if raw in (False, None, 0, "", "0", "false", "False"):
                setattr(self, name, False)
            else:
                setattr(self, name, bool(raw))

    def save(self, path: Path | None = None, async_write: bool = False) -> None:
        self._clamp()
        path = path or app_data_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
        text = json.dumps(payload, indent=2)

        def _do_write() -> None:
            tmp = path.with_suffix(f".tmp_{os.getpid()}")
            try:
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(path)
            except Exception:
                path.write_text(text, encoding="utf-8")

        if async_write:
            import threading
            threading.Thread(target=_do_write, daemon=True, name="settings-save").start()
        else:
            _do_write()

    def save_async(self, path: Path | None = None) -> None:
        """Non-blocking background save to prevent main UI thread stalls."""
        self.save(path=path, async_write=True)

