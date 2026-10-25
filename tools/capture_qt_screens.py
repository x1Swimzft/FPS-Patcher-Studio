"""Capture the Qt UI screenshot matrix into ``images/after-qt/``.

Run once per scale factor (Qt reads ``QT_SCALE_FACTOR`` at startup)::

    uv run python tools/capture_qt_screens.py --scale 1.0
    uv run python tools/capture_qt_screens.py --scale 1.25

Each run captures every preset x appearance x language combination. The 100%
run also captures one rich-queue hero image. Settings and queue state live in a
throwaway APPDATA directory so the real user profile is never read or written.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PRESETS = (
    ("Obsidian", "obsidian"),
    ("Midnight Violet", "midnight-violet"),
    ("Emerald Terminal", "emerald-terminal"),
    ("Crimson Gamer", "crimson-gamer"),
    ("Graphite", "graphite"),
    ("Amber Warm", "amber-warm"),
    ("Light", "light"),
)
MODES = ("light", "dark")
LANGUAGES = ("en", "th")
MAIN_SIZE = (1120, 760)
SETTINGS_SIZE = (920, 640)
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "images" / "after-qt"
BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
# The offscreen platform plugin does not expose installed system fonts. Load a
# Thai-capable family so the `th` matrix renders glyphs instead of tofu boxes.
THAI_FONT_FILES = ("LeelawUI.ttf", "leelawad.ttf", "tahoma.ttf")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        choices=(1.0, 1.25),
        help="Device scale factor for this process (default: 1.0)",
    )
    return parser.parse_args()


def _isolate_environment(scale: float, root: Path) -> None:
    """Point every writable location at ``root`` before importing the app."""
    appdata = root / "appdata"
    localappdata = root / "localappdata"
    for folder in (appdata, localappdata, root / "xdg", root / "qsettings"):
        folder.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(appdata)
    os.environ["LOCALAPPDATA"] = str(localappdata)
    os.environ["XDG_CONFIG_HOME"] = str(root / "xdg")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    # Put the bundled binaries first so shutil.which() cannot stall on a
    # disconnected network path while the FFmpeg locator scans PATH.
    if (BIN_DIR / "ffprobe.exe").is_file():
        os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


def _settings(preset: str, appearance: str, language: str, scale: float):
    from fps_patcher.config import Settings

    return Settings(
        theme_preset=preset,
        appearance=appearance,
        language=language,
        ui_scale=round(scale * 100),
        ffmpeg_dir=str(BIN_DIR) if (BIN_DIR / "ffmpeg.exe").is_file() else "",
        remember_geometry=False,
        check_ffmpeg_on_start=False,
        check_updates_on_start=False,
        watch_folder_enabled=False,
        explorer_menu=False,
        reduce_motion=False,
    )


def _load_thai_fonts() -> list[str]:
    from PySide6.QtGui import QFontDatabase

    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    families: list[str] = []
    for name in THAI_FONT_FILES:
        path = fonts_dir / name
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


def _grab(widget, target: Path) -> None:
    pixmap = widget.grab()
    if not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"could not save {target}")


def _wait_for_ffmpeg(window) -> None:
    """Let the background FFmpeg check settle so the badge is deterministic."""
    from PySide6.QtTest import QTest

    for _ in range(60):
        if window._ff_state != "checking":
            return
        QTest.qWait(50)


def _clear_queue_file() -> None:
    from fps_patcher.config import app_data_dir

    (app_data_dir() / "queue.json").unlink(missing_ok=True)


def _close_window(window) -> None:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window.close()
    window.deleteLater()
    QApplication.processEvents()
    QTest.qWait(30)


def _capture_combo(
    window_cls, dialog_cls, preset: str, slug: str, mode: str, lang: str, scale: float
) -> list[Path]:
    from PySide6.QtTest import QTest

    _clear_queue_file()
    settings = _settings(preset, mode, lang, scale)
    window = window_cls(settings)
    window.resize(*MAIN_SIZE)
    window.show()
    QTest.qWait(250)
    _wait_for_ffmpeg(window)

    tag = f"{slug}-{mode}-{lang}-{round(scale * 100)}"
    main_path = OUTPUT_DIR / f"{tag}-main.png"
    _grab(window, main_path)

    dialog = dialog_cls(settings, window.theme_manager)
    dialog.setModal(False)
    dialog.resize(*SETTINGS_SIZE)
    dialog.show()
    QTest.qWait(250)
    settings_path = OUTPUT_DIR / f"{tag}-settings.png"
    _grab(dialog, settings_path)

    dialog.hide()
    dialog.deleteLater()
    QTest.qWait(30)
    _close_window(window)
    return [main_path, settings_path]


def _fake_video_info(path: Path, *, fps: int, duration: float, size_mb: int):
    from fractions import Fraction

    from fps_patcher.core.models import VideoInfo

    frames = int(fps * duration)
    size_bytes = size_mb * 1024 * 1024
    return VideoInfo(
        path=path,
        codec="h264",
        width=1920,
        height=1080,
        avg_fps=Fraction(fps, 1),
        r_fps=Fraction(fps, 1),
        duration_s=duration,
        timescale=90000,
        nb_frames=frames,
        has_audio=True,
        stream_count=2,
        audio_codec="aac",
        bit_rate=size_bytes * 8 // max(1, int(duration)),
        audio_sample_rate=48000,
        audio_channels=2,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        color_primaries="bt709",
        color_transfer="bt709",
        color_space="bt709",
        pix_fmt="yuv420p",
        file_size_bytes=size_bytes,
    )


def _make_clip(path: Path, color: str) -> None:
    """Write a real short clip so the rich-queue hero shows real thumbnails."""
    ffmpeg = BIN_DIR / "ffmpeg.exe"
    if ffmpeg.is_file():
        subprocess.run(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d=2",
                "-c:v", "mpeg4", str(path),
            ],
            check=False,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if not path.is_file():
        path.write_bytes(b"\0" * 1024)


def _capture_rich_queue(window_cls, scale: float, root: Path) -> Path:
    from PySide6.QtTest import QTest

    from fps_patcher.app.queue_model import InputQueue

    media = root / "media"
    media.mkdir(parents=True, exist_ok=True)
    names = ("ranked_finals_60fps.mp4", "boss_fight_120fps.mp4", "victory_screen_60fps.mp4")
    colors = ("navy", "darkgreen", "maroon")
    paths = []
    for name, color in zip(names, colors, strict=True):
        path = media / name
        _make_clip(path, color)
        paths.append(path)

    _clear_queue_file()
    settings = _settings("Crimson Gamer", "dark", "en", scale)
    window = window_cls(settings)
    window.resize(*MAIN_SIZE)
    window.show()
    QTest.qWait(250)
    _wait_for_ffmpeg(window)

    queue = InputQueue()
    queue.add(paths)
    specs = (
        ("ready", 0.0, None, _fake_video_info(paths[0], fps=60, duration=42.5, size_mb=184)),
        ("patching", 0.42, None, _fake_video_info(paths[1], fps=120, duration=95.0, size_mb=512)),
        (
            "done",
            1.0,
            media / "victory_screen_60fps_60fps.mp4",
            _fake_video_info(paths[2], fps=60, duration=18.0, size_mb=96),
        ),
    )
    for path, (status, progress, output, info) in zip(paths, specs, strict=True):
        queue.set_info(path, info)
        queue.set_status(path, status, output=output)
        item = queue.get(path)
        if item is not None:
            item.progress = progress

    window.controller.items = queue
    window.controller.queue = queue.paths()
    # Show the inspector override card in its active state on the focused row.
    queue.set_override(paths[0], timescale=60000, strategy="bxd-mobile")
    window.queue_view.refresh()
    window.queue_view._focus_row(0, open_player=False)
    window._refresh_readiness()
    for _ in range(80):
        if all(window.queue_view.thumbnail(item.item_id) for item in queue.items):
            break
        QTest.qWait(100)

    target = OUTPUT_DIR / f"crimson-gamer-dark-en-{round(scale * 100)}-main-queue.png"
    _grab(window, target)
    _close_window(window)
    return target


def _validate(path: Path, expected: tuple[int, int]):
    from PIL import Image, ImageStat

    if not path.is_file():
        return False, "missing", 0, 0.0
    size_bytes = path.stat().st_size
    if size_bytes == 0:
        return False, "empty file", 0, 0.0
    try:
        with Image.open(path) as image:
            width, height = image.size
            hist = ImageStat.Stat(image.convert("RGB"))
            spread = max(hist.stddev) if hist.stddev else 0.0
    except Exception as exc:  # pragma: no cover - corrupt PNG is the failure
        return False, f"unreadable ({exc})", size_bytes, 0.0
    if abs(width - expected[0]) > 2 or abs(height - expected[1]) > 2:
        return False, f"size {width}x{height} != {expected[0]}x{expected[1]}", size_bytes, spread
    if spread <= 2.0:
        return False, f"blank (stddev {spread:.2f})", size_bytes, spread
    return True, "ok", size_bytes, spread


def _suppress_registry_side_effects(window_cls) -> None:
    # `explorer_menu=False` makes MainWindow call shell_integration.uninstall(),
    # which would delete a real HKCU Explorer verb. Captures must not touch the
    # registry; this is the only startup path that does.
    window_cls._sync_explorer_menu = lambda self: None


def main() -> int:
    args = _parse_args()
    root = Path(tempfile.mkdtemp(prefix="fps-capture-"))
    _isolate_environment(args.scale, root)

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from fps_patcher.ui_qt.main_window import MainWindow
    from fps_patcher.ui_qt.settings_dialog import SettingsDialog

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / "qsettings")
    )
    _suppress_registry_side_effects(MainWindow)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("FPSPatcherStudio")
    app.setOrganizationName("FPSPatcherStudio")

    print("Thai font families:", ", ".join(_load_thai_fonts()) or "none found")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scale_tag = round(args.scale * 100)
    for stale in OUTPUT_DIR.glob(f"*-{scale_tag}-*.png"):
        stale.unlink()

    expected_main = (round(MAIN_SIZE[0] * args.scale), round(MAIN_SIZE[1] * args.scale))
    expected_settings = (
        round(SETTINGS_SIZE[0] * args.scale),
        round(SETTINGS_SIZE[1] * args.scale),
    )

    captured: list[tuple[str, Path]] = []
    try:
        for preset, slug in PRESETS:
            for mode in MODES:
                for lang in LANGUAGES:
                    for target in _capture_combo(
                        MainWindow, SettingsDialog, preset, slug, mode, lang, args.scale
                    ):
                        captured.append((f"{slug}-{mode}-{lang}", target))
        if args.scale == 1.0:
            captured.append(("rich-queue", _capture_rich_queue(MainWindow, args.scale, root)))
    finally:
        app.processEvents()

    print(f"\nScale {args.scale:g} — validating {len(captured)} PNGs")
    header = f"{'combination':<32} {'kind':<8} {'px':>12} {'KB':>8} {'stddev':>7}  result"
    print(header)
    print("-" * len(header))
    failures = 0
    for name, path in captured:
        expected = expected_settings if path.name.endswith("-settings.png") else expected_main
        ok, detail, size_bytes, spread = _validate(path, expected)
        kind = "settings" if path.name.endswith("-settings.png") else "main"
        print(
            f"{name:<32} {kind:<8} {str(expected):>12} "
            f"{size_bytes / 1024:>8.1f} {spread:>7.2f}  {detail}"
        )
        if not ok:
            failures += 1

    print(f"\n{len(captured) - failures}/{len(captured)} passed, {failures} failed")
    shutil.rmtree(root, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
