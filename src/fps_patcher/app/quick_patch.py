"""Headless one-shot patch used by ``--quick-patch`` and the Explorer verb.

Import graph rule: this module must never import ``fps_patcher.ui`` or tkinter.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..config import Settings
from ..core.errors import FFmpegNotFoundError, FPSPatcherError
from ..core.ffmpeg_locator import FFmpegPaths, locate
from ..core.models import PatchRequest, PatchResult
from ..core.notify import toast
from ..core.patcher import patch

QUICK_PATCH_TIMESCALE = 60000


def _ignore(_event: object) -> None:
    return None


def _ffmpeg(settings: Settings) -> FFmpegPaths | None:
    try:
        return locate(Path(settings.ffmpeg_dir) if settings.ffmpeg_dir else None)
    except FFmpegNotFoundError:
        return None


def _request(path: Path, settings: Settings) -> PatchRequest:
    return PatchRequest(
        src=path,
        out_dir=Path(settings.output_dir) if settings.output_dir else path.parent,
        timescale=QUICK_PATCH_TIMESCALE,
        strategy=settings.strategy,
        overwrite=settings.overwrite,
        auto_rename=settings.auto_rename,
        v4_strict_lossless=settings.v4_strict_lossless,
        v4_preserve_video=settings.v4_preserve_video,
        v4_preserve_audio=settings.v4_preserve_audio,
        v4_sync_mvhd=settings.v4_sync_mvhd,
        v4_export_report=settings.v4_export_report,
        v4_dry_run=settings.v4_dry_run,
        bxd_padding_bytes=settings.bxd_padding_bytes,
        bxd_max_tail_ms=settings.bxd_max_tail_ms,
        auto_normalize_audio=settings.auto_normalize_audio,
        auto_cap_bitrate=settings.auto_cap_bitrate,
        fix_color_tag=settings.fix_color_tag,
        scrub_metadata=settings.scrub_metadata,
    )


def run(path: Path, settings: Settings | None = None, *, show_toast: bool = True) -> int:
    """Patch one file headlessly. Returns 0 on success, 1 on any failure."""
    path = Path(path)
    settings = settings or Settings.load()
    try:
        result: PatchResult = patch(_request(path, settings), _ffmpeg(settings), _ignore)
        if show_toast:
            toast(f"X1T quick patch complete: {result.output.name}")
        print(f"Patched: {result.output}")
        return 0
    except (FPSPatcherError, OSError) as exc:
        if show_toast:
            toast(f"X1T quick patch failed: {path.name} — {exc}")
        print(f"Quick patch failed: {exc}", file=sys.stderr)
        return 1
