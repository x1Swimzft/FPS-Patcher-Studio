from __future__ import annotations

import threading
import time
from fractions import Fraction
from pathlib import Path

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import (
    Event,
    LogEvent,
    PatchDoneEvent,
    PatchRequest,
    PatchResult,
    ProbeDoneEvent,
    ProgressEvent,
    VideoInfo,
)


def _wait_for(ctrl: AppController, kind: type, timeout: float = 20) -> list[Event]:
    seen: list[Event] = []
    end = time.time() + timeout
    while time.time() < end:
        ctrl.drain(seen.append)
        if any(isinstance(e, kind) for e in seen):
            return seen
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for {kind.__name__}: {seen}")


def test_controller_probe_and_patch(clip30: Path, tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.load_file(clip30)
    events = _wait_for(ctrl, ProbeDoneEvent)
    assert ctrl.current is not None and round(ctrl.current.fps) == 30

    ctrl.start_patch(60000, "timescale")
    events = _wait_for(ctrl, PatchDoneEvent)
    done = next(e for e in events if isinstance(e, PatchDoneEvent))
    assert done.result is not None, done.error
    assert done.result.output.parent == tmp_path
    assert done.result.after.timescale == 60000


def test_controller_batch_queue(clip30: Path, clip5994: Path, tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.load_files([clip30, clip5994])
    probe_events = _wait_for(ctrl, ProbeDoneEvent)
    probe_done = next(e for e in probe_events if isinstance(e, ProbeDoneEvent))
    assert probe_done.queue_count == 2
    assert len(ctrl.queue) == 2

    ctrl.start_patch(120000, "timescale")
    patch_events = _wait_for(ctrl, PatchDoneEvent)
    done = next(e for e in patch_events if isinstance(e, PatchDoneEvent))
    assert done.result is not None, done.error
    assert len(done.batch_results) == 2
    assert done.total_files == 2
    assert all(r.after.timescale == 120000 for r in done.batch_results)

    # Per-file progress events were emitted
    progresses = [e for e in patch_events if isinstance(e, ProgressEvent)]
    assert len(progresses) > 0
    assert any(p.file_index == 1 for p in progresses)
    assert any(p.file_index == 2 for p in progresses)


def test_controller_batch_cancel(clip30: Path, clip5994: Path, tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.load_files([clip30, clip5994])
    _wait_for(ctrl, ProbeDoneEvent)

    orig_emit = ctrl.emit

    # Set cancel flag as soon as file 1 completes its run
    def wrapped_emit(evt: Event) -> None:
        orig_emit(evt)
        if isinstance(evt, LogEvent) and "Done in" in evt.message:
            ctrl._cancel.set()

    ctrl.emit = wrapped_emit  # type: ignore[assignment,method-assign]

    ctrl.start_patch(60000, "timescale")
    patch_events = _wait_for(ctrl, PatchDoneEvent)
    done = next(e for e in patch_events if isinstance(e, PatchDoneEvent))

    assert done.cancelled is True
    assert len(done.batch_results) == 1
    assert len(list(tmp_path.glob("*.part"))) == 0


def test_shutdown_cancels_and_joins_the_worker() -> None:
    ctrl = AppController(Settings())
    started = threading.Event()

    def job() -> None:
        started.set()
        ctrl._cancel.wait(5)

    ctrl._start(job)
    assert started.wait(2)

    ctrl.shutdown(timeout=2)

    assert not ctrl.busy


def test_controller_batch_with_bad_file(clip30: Path, tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    bad_mp4 = tmp_path / "bad_clip.mp4"
    bad_mp4.write_text("invalid video stream data", encoding="utf-8")

    ctrl.load_files([bad_mp4, clip30])
    _wait_for(ctrl, ProbeDoneEvent)

    ctrl.start_patch(60000, "timescale")
    patch_events = _wait_for(ctrl, PatchDoneEvent)
    done = next(e for e in patch_events if isinstance(e, PatchDoneEvent))

    assert len(done.failed) == 1
    assert done.failed[0][0] == bad_mp4
    assert len(done.batch_results) == 1
    assert done.batch_results[0].src == clip30


def test_controller_settings_reach_patch_request(
    clip30: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []

    def mock_patch(req: PatchRequest, *args: object, **kwargs: object) -> PatchResult:
        captured.append(req)
        dummy = VideoInfo(
            path=req.src,
            codec="h264",
            width=320,
            height=240,
            avg_fps=Fraction(30),
            r_fps=Fraction(30),
            duration_s=1.0,
            timescale=req.timescale,
            nb_frames=30,
            has_audio=True,
            stream_count=2,
        )
        return PatchResult(
            src=req.src,
            output=req.src,
            before=dummy,
            after=dummy,
            elapsed_s=0.05,
        )

    monkeypatch.setattr("fps_patcher.app.controller.patch", mock_patch)

    ctrl = AppController(Settings(output_dir=str(tmp_path), overwrite=True, auto_rename=False))
    ctrl.init_ffmpeg()
    ctrl.load_file(clip30)
    _wait_for(ctrl, ProbeDoneEvent)

    ctrl.start_patch(60000, "timescale")
    _wait_for(ctrl, PatchDoneEvent)

    assert len(captured) == 1
    assert captured[0].overwrite is True
    assert captured[0].auto_rename is False


def test_controller_ffmpeg_missing_error(clip30: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_locate(_: Path | None = None) -> FFmpegPaths:
        from fps_patcher.core.errors import FFmpegNotFoundError

        raise FFmpegNotFoundError("FFmpeg not found.")

    monkeypatch.setattr("fps_patcher.app.controller.locate", fake_locate)
    ctrl = AppController(Settings())
    paths = ctrl.init_ffmpeg()
    assert paths is None

    # Probing when ffmpeg is missing uses direct container parser
    ctrl.load_file(clip30)
    seen = _wait_for(ctrl, ProbeDoneEvent)
    assert any(
        isinstance(e, LogEvent) and "direct MP4 container parser" in e.message
        for e in seen
    )

    # Patching with FFmpeg-dependent strategy emits error log
    ctrl.start_patch(60000, "timescale")
    seen2: list[Event] = []
    ctrl.drain(seen2.append)
    assert any(
        isinstance(e, LogEvent) and e.level == "ERROR" and "requires FFmpeg" in e.message
        for e in seen2
    )


def test_controller_rejects_bad_ext(tmp_path: Path) -> None:
    ctrl = AppController(Settings())
    ctrl.init_ffmpeg()
    ctrl.load_file(tmp_path / "x.avi")
    seen: list[Event] = []
    ctrl.drain(seen.append)
    assert any(isinstance(e, LogEvent) and e.level == "ERROR" for e in seen)


def test_settings_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    Settings(
        output_dir="X",
        custom_timescale=12345,
        overwrite=True,
        auto_rename=False,
    ).save(p)
    s = Settings.load(p)
    assert s.output_dir == "X" and s.custom_timescale == 12345
    assert s.overwrite is True and s.auto_rename is False
    p.write_text("{bad json", encoding="utf-8")
    assert Settings.load(p) == Settings()
