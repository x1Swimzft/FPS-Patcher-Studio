"""Bridges UI (main thread) and core (worker threads) through a queue.

Tk is not thread-safe: workers only ever ``put`` events; the main thread
drains the queue via ``drain()`` scheduled with ``after``.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from ..config import Settings
from ..core.errors import (
    FFmpegNotFoundError,
    FPSPatcherError,
    OutputFileExistsError,
    PatchCancelledError,
    PatchError,
)
from ..core.ffmpeg_downloader import DOWNLOAD_URL, download_ffmpeg
from ..core.ffmpeg_locator import FFmpegPaths, locate
from ..core.models import (
    SUPPORTED_EXTENSIONS,
    Event,
    FFmpegDownloadEvent,
    LogEvent,
    LogLevel,
    PatchDoneEvent,
    PatchRequest,
    PatchResult,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
    VideoInfo,
)
from ..core.patcher import patch
from ..core.prober import probe
from ..core.strategies import strategy_requires_ffmpeg
from .queue_model import AddResult, InputQueue

log = logging.getLogger("fps_patcher")

EventHandler = Callable[[Event], None]


class AppController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.events: queue.Queue[Event] = queue.Queue()
        self.ffmpeg: FFmpegPaths | None = None
        self.current: VideoInfo | None = None
        self.queue: list[Path] = []
        self.items = InputQueue()
        self.current_patching_path: Path | None = None
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._ff_download: threading.Thread | None = None

        mig = getattr(self.settings, "migrated_strategy_from", None)
        if mig:
            extra = (
                " (modifies MP4 timing atoms directly instead of FFmpeg stream copy)"
                if mig in ("ffmpeg-copy", "timescale", "timescale+movie")
                else ""
            )
            self.emit(
                LogEvent(
                    f"Notice: Legacy strategy '{mig}' was migrated to preset "
                    f"'{self.settings.strategy}'{extra}.",
                    "WARN",
                )
            )
            self.settings.migrated_strategy_from = None

    # ---------- state ----------
    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def emit(self, event: Event) -> None:
        self.events.put(event)
        if isinstance(event, LogEvent):
            log.log(logging.ERROR if event.level == "ERROR" else logging.INFO, event.message)

    def drain(self, handler: EventHandler, limit: int = 500) -> None:
        """Main-thread only. Updates controller state, then forwards to UI."""
        for _ in range(limit):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, ProbeDoneEvent):
                self.current = event.info
            elif isinstance(event, PatchDoneEvent):
                if event.result:
                    self.current = event.result.after
                self._worker = None
            elif isinstance(event, FFmpegDownloadEvent) and event.paths is not None:
                self.ffmpeg = event.paths
            handler(event)

    # ---------- ffmpeg ----------
    def init_ffmpeg(self) -> FFmpegPaths | None:
        custom = Path(self.settings.ffmpeg_dir) if self.settings.ffmpeg_dir else None
        try:
            self.ffmpeg = locate(custom)
            self.emit(LogEvent(f"FFmpeg: {self.ffmpeg.ffmpeg}", "OK"))
            self.emit(LogEvent(self.ffmpeg.version, "DEBUG"))
        except FFmpegNotFoundError as exc:
            self.ffmpeg = None
            self.emit(LogEvent(str(exc), "ERROR"))
        return self.ffmpeg

    @property
    def ffmpeg_downloading(self) -> bool:
        return self._ff_download is not None and self._ff_download.is_alive()

    def start_ffmpeg_download(self) -> None:
        """Download + install FFmpeg on a background thread; result via FFmpegDownloadEvent."""
        if self.ffmpeg_downloading:
            return
        custom = Path(self.settings.ffmpeg_dir) if self.settings.ffmpeg_dir else None

        def job() -> None:
            last: tuple[int, str] = (-1, "")

            def on_progress(done: int, total: int, stage: str) -> None:
                nonlocal last
                evt = FFmpegDownloadEvent(stage, done, total)
                if (evt.percent, stage) != last:  # throttle to percent/stage changes
                    last = (evt.percent, stage)
                    self.emit(evt)

            self.emit(LogEvent(f"Downloading FFmpeg from {DOWNLOAD_URL}"))
            try:
                installed = download_ffmpeg(progress=on_progress)
                paths = locate(custom)  # re-probe honoring search priority
            except FPSPatcherError as exc:
                self.emit(LogEvent(f"FFmpeg download failed: {exc}", "ERROR"))
                self.emit(FFmpegDownloadEvent("error", error=str(exc)))
                return
            except Exception as exc:  # never let the worker die silently
                log.exception("Unexpected FFmpeg download failure")
                self.emit(LogEvent(f"FFmpeg download failed: {exc}", "ERROR"))
                self.emit(FFmpegDownloadEvent("error", error=str(exc)))
                return
            self.emit(LogEvent(f"FFmpeg installed: {installed.ffmpeg}", "OK"))
            self.emit(FFmpegDownloadEvent("done", paths=paths))

        self._ff_download = threading.Thread(target=job, daemon=True)
        self._ff_download.start()

    # ---------- multi-file queue (append, never replace) ----------
    def add_files(self, paths: list[Path], select: bool = True) -> AddResult:
        """Append files, skip duplicates, probe each new file in background."""
        res = self.items.add(paths)
        for p, why in res.rejected:
            self.emit(LogEvent(f"Rejected {p.name}: {why}", "ERROR"))
        if res.duplicates:
            self.emit(LogEvent(f"Skipped {len(res.duplicates)} duplicate file(s)", "WARN"))
        if not res.added:
            return res
        if select:
            for p in res.added:
                item = self.items.get(p)
                if item:
                    item.selected = True
        self.queue = self.items.paths()
        self.emit(QueueChangedEvent("added"))
        ffprobe_path = self.ffmpeg.ffprobe if self.ffmpeg else None
        new = list(res.added)

        def probe_all() -> None:
            for path in new:
                if self.items.get(path) is None:  # removed meanwhile
                    continue
                self.items.set_status(path, "probing")
                try:
                    info = probe(path, ffprobe_path)
                    self.items.set_info(path, info)
                    if info.bit_rate is not None and info.bit_rate > 25_000_000:
                        mbps = info.bit_rate / 1_000_000
                        self.emit(
                            LogEvent(
                                f"High bitrate detected ({mbps:.1f} Mbps > 25 Mbps) for "
                                f"{path.name}. Bypassed videos stream at source quality on "
                                "TikTok; bitrates >20 Mbps may cause buffering for mobile "
                                "viewers. Recommended: 12-18 Mbps for 1080p.",
                                "WARN",
                            )
                        )
                    if (
                        info.has_audio
                        and info.audio_codec
                        and info.audio_codec.lower() not in ("aac", "mp4a")
                    ):
                        self.emit(
                            LogEvent(
                                f"Non-AAC audio codec detected ('{info.audio_codec}') for "
                                f"{path.name}. TikTok may mute non-AAC audio when bypass is "
                                "active. Recommended: AAC 48kHz.",
                                "WARN",
                            )
                        )
                except FPSPatcherError as exc:
                    self.items.set_info(path, None, str(exc))
                    self.emit(LogEvent(f"Probe failed {path.name}: {exc}", "ERROR"))
                self.emit(QueueChangedEvent("probed"))

        threading.Thread(target=probe_all, daemon=True).start()
        return res

    def remove_selected(self) -> int:
        n = self.items.remove_selected(locked_path=self.current_patching_path)
        self.queue = self.items.paths()
        self.emit(QueueChangedEvent("removed"))
        return n

    def clear_queue(self) -> None:
        if self.busy:
            return
        self.items.clear(locked_path=self.current_patching_path)
        self.queue = self.items.paths()
        self.current = None
        self.emit(QueueChangedEvent("cleared"))

    # ---------- actions ----------
    def load_file(self, path: Path) -> None:
        self.load_files([path])

    def load_files(self, paths: list[Path]) -> None:
        if self.busy:
            self.emit(LogEvent("Busy; wait for current job to finish.", "WARN"))
            return

        valid_paths: list[Path] = []
        for p in paths:
            if not p.is_file():
                self.emit(LogEvent(f"File not found: {p}", "ERROR"))
            elif p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                self.emit(
                    LogEvent(
                        f"Unsupported file type '{p.suffix}' for '{p.name}'. Supported: "
                        + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
                        "ERROR",
                    )
                )
            else:
                valid_paths.append(p)

        if not valid_paths:
            return

        if self.ffmpeg is None:
            self.emit(
                LogEvent(
                    "FFmpeg not configured. Using direct MP4 container parser.",
                    "INFO",
                )
            )

        self.queue = valid_paths
        ffprobe_path = self.ffmpeg.ffprobe if self.ffmpeg else None
        if len(valid_paths) == 1:
            self.emit(LogEvent(f"Loaded: {valid_paths[0]}"))
        else:
            self.emit(LogEvent(f"Loaded batch: {len(valid_paths)} files queued"))

        def probe_job() -> None:
            first_path = valid_paths[0]
            try:
                info = probe(first_path, ffprobe_path)
                if info.bit_rate is not None and info.bit_rate > 25_000_000:
                    mbps = info.bit_rate / 1_000_000
                    self.emit(
                        LogEvent(
                            f"High bitrate detected ({mbps:.1f} Mbps > 25 Mbps) for "
                            f"{first_path.name}. Bypassed videos stream at source quality on "
                            "TikTok; bitrates >20 Mbps may cause buffering for mobile "
                            "viewers. Recommended: 12-18 Mbps for 1080p.",
                            "WARN",
                        )
                    )
                if (
                    info.has_audio
                    and info.audio_codec
                    and info.audio_codec.lower() not in ("aac", "mp4a")
                ):
                    self.emit(
                        LogEvent(
                            f"Non-AAC audio codec detected ('{info.audio_codec}') for "
                            f"{first_path.name}. TikTok may mute non-AAC audio when bypass "
                            "is active. Recommended: AAC 48kHz.",
                            "WARN",
                        )
                    )
                self.emit(
                    ProbeDoneEvent(
                        info=info,
                        queue_count=len(valid_paths),
                        queue_paths=valid_paths,
                    )
                )
            except FPSPatcherError as exc:
                self.emit(
                    ProbeDoneEvent(
                        info=None,
                        error=str(exc),
                        queue_count=len(valid_paths),
                        queue_paths=valid_paths,
                    )
                )

        self._start(probe_job)

    def start_patch(
        self,
        timescale: int,
        strategy: str,
        overwrite: bool | None = None,
        auto_rename: bool | None = None,
        only_selected: bool = True,
    ) -> None:
        if self.busy:
            return
        if strategy_requires_ffmpeg(strategy) and self.ffmpeg is None:
            self.emit(
                LogEvent(
                    f"Strategy '{strategy}' requires FFmpeg. Please select the folder "
                    "containing ffmpeg.exe or select a direct atom strategy.",
                    "ERROR",
                )
            )
            return

        if self.items:
            items = [i.path for i in self.items.snapshot_for_run(only_selected)]
            if not items:
                msg = (
                    "No selected files to patch."
                    if only_selected
                    else "No files to patch (all queue items already done)."
                )
                self.emit(LogEvent(msg, "WARN"))
                return
            self.items.reset_for_run(items)
            self.emit(QueueChangedEvent("reset"))
        else:
            fallback = [self.current.path] if self.current else []
            items = list(self.queue) if self.queue else fallback
        if not items:
            self.emit(LogEvent("No files to patch.", "WARN"))
            return

        eff_overwrite = self.settings.overwrite if overwrite is None else overwrite
        eff_auto_rename = self.settings.auto_rename if auto_rename is None else auto_rename

        ff = self.ffmpeg
        total_files = len(items)
        self._cancel.clear()

        def patch_job() -> None:
            batch_results: list[PatchResult] = []
            failed: list[tuple[Path, str]] = []
            cancelled = False
            last_error: str | None = None
            last_stderr: list[str] = []

            try:
                for idx, src in enumerate(items, start=1):
                    if self._cancel.is_set():
                        cancelled = True
                        self.emit(
                            LogEvent(
                                f"Batch cancelled by user before file {idx}/{total_files} "
                                f"({src.name})",
                                "WARN",
                            )
                        )
                        break

                    self.current_patching_path = src
                    out_dir = (
                        Path(self.settings.output_dir)
                        if self.settings.output_dir
                        else src.parent
                    )
                    qi = self.items.get(src)
                    req = PatchRequest(
                        src=src,
                        out_dir=out_dir,
                        timescale=(qi.timescale if qi and qi.timescale else timescale),
                        strategy=(qi.strategy if qi and qi.strategy else strategy),
                        overwrite=eff_overwrite,
                        auto_rename=eff_auto_rename,
                        v4_strict_lossless=self.settings.v4_strict_lossless,
                        v4_preserve_video=self.settings.v4_preserve_video,
                        v4_preserve_audio=self.settings.v4_preserve_audio,
                        v4_sync_mvhd=self.settings.v4_sync_mvhd,
                        v4_export_report=self.settings.v4_export_report,
                        v4_dry_run=self.settings.v4_dry_run,
                        bxd_padding_bytes=self.settings.bxd_padding_bytes,
                        bxd_max_tail_ms=self.settings.bxd_max_tail_ms,
                    )

                    self.emit(LogEvent(f"[{idx}/{total_files}] Starting patch for {src.name}"))

                    def file_emit(
                        evt: LogEvent | ProgressEvent,
                        cur_idx: int = idx,
                        cur_src: Path = src,
                    ) -> None:
                        if isinstance(evt, ProgressEvent):
                            overall = ((cur_idx - 1) + evt.fraction) / total_files
                            self.emit(
                                ProgressEvent(
                                    fraction=overall,
                                    file_fraction=evt.fraction,
                                    current_file=cur_src,
                                    file_index=cur_idx,
                                    total_files=total_files,
                                )
                            )
                        else:
                            self.emit(evt)

                    try:
                        self.items.set_status(src, "patching")
                        self.emit(QueueChangedEvent("patching"))
                        res = patch(req, ff, file_emit, self._cancel)
                        batch_results.append(res)
                        self.items.set_status(src, "done", output=res.output)
                        self.emit(QueueChangedEvent("done"))
                    except PatchCancelledError as exc:
                        cancelled = True
                        last_error = str(exc)
                        self.emit(LogEvent(f"[{idx}/{total_files}] Cancelled {src.name}", "WARN"))
                        break
                    except OutputFileExistsError as exc:
                        last_error = str(exc)
                        failed.append((src, str(exc)))
                        self.items.set_status(src, "failed", error=str(exc))
                        self.emit(
                            LogEvent(
                                f"[{idx}/{total_files}] Output exists error for {src.name}: {exc}",
                                "ERROR",
                            )
                        )
                    except PatchError as exc:
                        last_error = str(exc)
                        last_stderr = exc.stderr_tail
                        failed.append((src, str(exc)))
                        self.items.set_status(src, "failed", error=str(exc))
                        self.emit(
                            LogEvent(f"[{idx}/{total_files}] Failed {src.name}: {exc}", "ERROR")
                        )
                    except FPSPatcherError as exc:
                        last_error = str(exc)
                        failed.append((src, str(exc)))
                        self.items.set_status(src, "failed", error=str(exc))
                        self.emit(
                            LogEvent(
                                f"[{idx}/{total_files}] Verification failed for {src.name}: {exc}",
                                "ERROR",
                            )
                        )
                    except Exception as exc:
                        log.exception("Unexpected patch failure in batch")
                        last_error = f"Unexpected error: {exc}"
                        failed.append((src, last_error))
                        self.items.set_status(src, "failed", error=last_error)
                        self.emit(
                            LogEvent(
                                f"[{idx}/{total_files}] Unexpected error {src.name}: {exc}",
                                "ERROR",
                            )
                        )
                    finally:
                        self.current_patching_path = None
            finally:
                self.current_patching_path = None

            n_exp = sum(1 for r in batch_results if r.experimental)
            n_ok = len(batch_results) - n_exp
            summary = f"Batch summary: {n_ok} ok, {len(failed)} failed"
            if n_exp:
                summary = (
                    f"Batch summary: {n_ok} ok, {n_exp} done (experimental), "
                    f"{len(failed)} failed"
                )
            if failed:
                summary_level: LogLevel = "WARN" if batch_results else "ERROR"
            else:
                summary_level = "WARN" if n_exp else "OK"
            self.emit(LogEvent(summary, summary_level))

            last_res = batch_results[-1] if batch_results else None
            if cancelled:
                self.emit(
                    PatchDoneEvent(
                        result=last_res,
                        error=last_error if last_error else "Batch cancelled by user.",
                        batch_results=batch_results,
                        failed=failed,
                        total_files=total_files,
                        cancelled=True,
                    )
                )
            elif not batch_results and last_error:
                self.emit(
                    PatchDoneEvent(
                        result=None,
                        error=last_error,
                        stderr_tail=last_stderr,
                        batch_results=[],
                        failed=failed,
                        total_files=total_files,
                        cancelled=False,
                    )
                )
            else:
                self.emit(
                    PatchDoneEvent(
                        result=last_res,
                        error=last_error,
                        stderr_tail=last_stderr,
                        batch_results=batch_results,
                        failed=failed,
                        total_files=total_files,
                        cancelled=False,
                    )
                )

        self._start(patch_job)

    def repair_file_for_mobile(self, src: Path, out: Path | None = None) -> Path | None:
        """Repair a BXD PC-only clip into a clean mobile-compatible MP4."""
        from ..core.bxd_patcher import repair_for_mobile
        from ..core.diagnostic_logger import auto_save_diagnostic_log

        if out is None:
            out_dir = Path(self.settings.output_dir) if self.settings.output_dir else src.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{src.stem}_mobile_repaired{src.suffix}"
            n = 1
            while out.exists() and not self.settings.overwrite:
                out = out_dir / f"{src.stem}_mobile_repaired ({n}){src.suffix}"
                n += 1

        logs: list[str] = []

        def emit_repair(msg: str) -> None:
            logs.append(msg)
            lvl: LogLevel = "OK" if msg.startswith("[SUCCESS") else "INFO"
            self.emit(LogEvent(msg, lvl))

        try:
            res = repair_for_mobile(src, out, emit=emit_repair)
            auto_save_diagnostic_log(
                file_path=out,
                console_lines=logs,
                orig_path=src,
                mask_paths=self.settings.mask_diagnostic_paths,
            )
            return Path(res["output"])
        except Exception as exc:
            self.emit(LogEvent(f"Mobile repair failed for {src.name}: {exc}", "ERROR"))
            auto_save_diagnostic_log(
                file_path=src,
                console_lines=[*logs, f"REPAIR ERROR: {exc}"],
                orig_path=src,
                mask_paths=self.settings.mask_diagnostic_paths,
            )
            return None

    def cancel(self) -> None:
        if self.busy:
            self._cancel.set()
            self.emit(LogEvent("Cancelling current operation...", "WARN"))

    def _start(self, job: Callable[[], None]) -> None:
        self._worker = threading.Thread(target=job, daemon=True)
        self._worker.start()

