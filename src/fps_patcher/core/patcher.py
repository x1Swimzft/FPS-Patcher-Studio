"""Orchestrates probe -> remux -> verify for one file. No UI dependencies."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .atom_patcher import patch_video_track_timescale
from .bxd_patcher import MethodBXDDirectPatch
from .errors import FFmpegNotFoundError, OutputFileExistsError, PatchError, VerifyError
from .ffmpeg_locator import FFmpegPaths
from .ffmpeg_runner import run_streaming
from .models import (
    SUPPORTED_EXTENSIONS,
    LogEvent,
    LogLevel,
    PatchRequest,
    PatchResult,
    ProgressEvent,
)
from .prober import probe
from .strategies import get_strategy
from .v4_patcher import MethodV4DirectPatch
from .verifier import verify, verify_payload_integrity

Emit = Callable[[LogEvent | ProgressEvent], None]


def validate_input(path: Path) -> None:
    if not path.is_file():
        raise PatchError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise PatchError(
            f"Unsupported file type '{path.suffix}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )


def output_path_for(req: PatchRequest) -> Path:
    """<stem>_ts<timescale><ext>; adds (n) suffix unless overwrite or no auto_rename."""
    base = req.out_dir / f"{req.src.stem}_ts{req.timescale}{req.src.suffix}"
    if req.overwrite or not base.exists():
        return base
    if not req.auto_rename:
        raise OutputFileExistsError(
            f"Output file already exists at '{base}'. Enable overwrite or allow auto-renaming."
        )
    n = 1
    while True:
        cand = base.with_name(f"{base.stem} ({n}){base.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _parse_progress(line: str, duration_s: float) -> float | None:
    key, _, value = line.partition("=")
    if key in ("out_time_us", "out_time_ms") and duration_s > 0:
        try:
            return min(max(int(value) / 1_000_000 / duration_s, 0.0), 1.0)
        except ValueError:
            return None
    if key == "progress" and value == "end":
        return 1.0
    return None


def patch(
    req: PatchRequest,
    paths: FFmpegPaths | None,
    emit: Emit,
    cancel_event: threading.Event | None = None,
) -> PatchResult:
    start = time.perf_counter()
    src = req.src
    validate_input(src)
    if req.timescale <= 0:
        raise PatchError("Timescale must be a positive integer.")
    req.out_dir.mkdir(parents=True, exist_ok=True)

    strategy = get_strategy(req.strategy)
    if not strategy.direct and paths is None:
        raise FFmpegNotFoundError(
            f"Strategy '{strategy.label}' requires FFmpeg executable, but FFmpeg is not configured."
        )

    emit(LogEvent(f"Probing {src.name}"))
    ffprobe_bin = paths.ffprobe if paths is not None else None
    before = probe(src, ffprobe_bin)
    emit(
        LogEvent(
            f"Source: {before.codec} {before.width}x{before.height} "
            f"{before.fps:.3f} fps, timescale {before.timescale}"
        )
    )
    if before.is_vfr:
        emit(LogEvent("Variable frame rate detected; result may differ per player.", "WARN"))

    final = output_path_for(req)
    if final.resolve() == src.resolve():
        raise PatchError(f"Output path equals source file ('{src}'); refusing to overwrite source.")
    tmp = final.with_name(final.name + ".part")
    tmp.unlink(missing_ok=True)

    emit(LogEvent(f"Strategy: {strategy.label}"))

    stderr_tail: deque[str] = deque(maxlen=15)

    def on_stdout(line: str) -> None:
        frac = _parse_progress(line, before.duration_s)
        if frac is not None:
            emit(ProgressEvent(frac))

    def on_stderr(line: str) -> None:
        stderr_tail.append(line)
        emit(LogEvent(line, "DEBUG"))

    try:
        if strategy.name == "v4-forensic":
            emit(LogEvent("Executing Method V4 Forensic Lossless Patch...", "INFO"))

            def v4_log(msg: str) -> None:
                lvl: LogLevel = "OK" if msg.startswith("[SUCCESS") else "DEBUG"
                emit(LogEvent(msg, lvl))

            v4_patcher = MethodV4DirectPatch(
                src=src,
                out=tmp,
                target_timescale=req.timescale,
                sync_mvhd=req.v4_sync_mvhd,
                strict_lossless=req.v4_strict_lossless,
                preserve_video=req.v4_preserve_video,
                preserve_audio=req.v4_preserve_audio,
                dry_run=req.v4_dry_run,
                export_report=req.v4_export_report,
                emit=v4_log,
                cancel_event=cancel_event,
            )
            v4_patcher.execute()
            if req.v4_dry_run:
                emit(LogEvent("Dry-run complete: no output file created.", "INFO"))
                return PatchResult(
                    src=src, output=src, before=before, after=before, elapsed_s=0.0
                )
        elif strategy.name in (
            "bxd-experimental",
            "bxd-pc",
            "bxd-mobile",
            "bxd-hybrid",
            "bxd-clean",
        ):
            emit(LogEvent(f"Executing {strategy.label}...", "INFO"))

            def bxd_log(msg: str) -> None:
                lvl: LogLevel = (
                    "OK"
                    if msg.startswith("[SUCCESS")
                    else ("WARN" if msg.startswith("[WARN") else "DEBUG")
                )
                emit(LogEvent(msg, lvl))

            bxd_patcher = MethodBXDDirectPatch(
                src=src,
                out=tmp,
                target_timescale=req.timescale,
                multiplier=10,
                indeterminate_mvhd=(strategy.name in ("bxd-experimental", "bxd-pc")),
                strip_edts=(strategy.name in ("bxd-experimental", "bxd-pc")),
                preset_mode=strategy.name,
                padding_bytes=req.bxd_padding_bytes,
                max_tail_ms=req.bxd_max_tail_ms,
                emit=bxd_log,
                cancel_event=cancel_event,
            )
            bxd_patcher.execute()
        elif strategy.name == "direct-atom":
            emit(LogEvent("Executing Method V3 Direct MP4 atom patch...", "INFO"))
            patch_video_track_timescale(src, tmp, req.timescale, cancel_event)
        else:
            if paths is None:
                raise FFmpegNotFoundError("FFmpeg executable required for stream copy.")
            args = strategy.build_args(req, before, tmp)
            emit(LogEvent("ffmpeg " + " ".join(f'"{a}"' if " " in a else a for a in args), "DEBUG"))
            code = run_streaming(paths.ffmpeg, args, on_stdout, on_stderr, cancel_event)
            if code != 0:
                raise PatchError(f"ffmpeg exited with code {code}", list(stderr_tail))

        after = probe(tmp, ffprobe_bin)
        dur_tol: float | None = None
        if strategy.name == "bxd-hybrid" and req.bxd_max_tail_ms > 0:
            dur_tol = max(0.25, (req.bxd_max_tail_ms / 1000.0) + 0.1)
        warnings = verify(before, after, req.timescale, duration_tolerance_s=dur_tol)
        for w in warnings:
            emit(LogEvent(w, "WARN"))

        # Output detailed payload integrity log
        integrity = verify_payload_integrity(src, tmp)
        experimental = any(status == "EXPERIMENTAL" for status in integrity.values())
        for item, status in integrity.items():
            level: LogLevel = (
                "OK" if status == "PASS" else ("WARN" if status == "EXPERIMENTAL" else "ERROR")
            )
            emit(LogEvent(f"[VERIFY] {item:<18} {status}", level))

        if final.exists():
            final.unlink()
        tmp.rename(final)
    except (PatchError, VerifyError) as exc:
        tmp.unlink(missing_ok=True)
        try:
            from .diagnostic_logger import auto_save_diagnostic_log

            auto_save_diagnostic_log(
                file_path=src,
                console_lines=[f"PATCH FAILED ({strategy.label}): {exc}", *list(stderr_tail)],
                orig_path=src,
            )
        except Exception:
            pass
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        try:
            from .diagnostic_logger import auto_save_diagnostic_log

            auto_save_diagnostic_log(
                file_path=src,
                console_lines=[f"UNEXPECTED ERROR ({strategy.label}): {exc}", *list(stderr_tail)],
                orig_path=src,
            )
        except Exception:
            pass
        raise PatchError(str(exc), list(stderr_tail)) from exc

    after = replace(after, path=final)
    elapsed = time.perf_counter() - start
    emit(ProgressEvent(1.0))
    done_msg = (
        f"Done{' (experimental, non-standard output)' if experimental else ''} "
        f"in {elapsed:.2f}s: timescale {before.timescale} -> {after.timescale}. "
        f"Output: {final}"
    )
    emit(LogEvent(done_msg, "WARN" if experimental else "OK"))

    try:
        from .diagnostic_logger import auto_save_diagnostic_log

        auto_save_diagnostic_log(
            file_path=final,
            console_lines=[f"Preset: {strategy.label}", done_msg],
            orig_path=src,
        )
    except Exception:
        pass

    return PatchResult(
        src=src,
        output=final,
        before=before,
        after=after,
        elapsed_s=elapsed,
        experimental=experimental,
    )

