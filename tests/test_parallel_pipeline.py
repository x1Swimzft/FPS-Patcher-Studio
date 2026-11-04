"""v2.0.0 Slice 6: two-stage parallel pipeline (GPU-serial preflight, parallel batch)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core import preflight
from fps_patcher.core.errors import PatchCancelledError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import (
    PatchDoneEvent,
    PatchRequest,
    ProgressEvent,
)
from fps_patcher.core.preflight import PreflightPlan, run_preflight


def _mk(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"x")
    return path


def _controller(tmp_path: Path, **overrides: Any) -> AppController:
    settings = Settings(output_dir=str(tmp_path), **overrides)
    return AppController(settings)


def _select(ctrl: AppController, paths: list[Path]) -> None:
    assert ctrl.items.add(paths).added
    ctrl.items.select_all(True)


def _run_to_done(ctrl: AppController, timeout: float = 10.0) -> list[object]:
    worker = ctrl._worker
    assert worker is not None
    worker.join(timeout)
    assert not worker.is_alive(), "patch worker did not finish"
    seen: list[object] = []
    ctrl.drain(seen.append, limit=100_000)
    return seen


def _done(events: list[object]) -> PatchDoneEvent:
    return next(e for e in events if isinstance(e, PatchDoneEvent))


def _fake_result(req: PatchRequest, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output=tmp_path / f"{req.src.stem}_{req.platform_profile}.mp4",
        experimental=False,
        after=None,
    )


# ---------- stage 1: preflight GPU semaphore ----------


def _preflight_paths(tmp_path: Path) -> FFmpegPaths:
    return FFmpegPaths(
        ffmpeg=tmp_path / "ffmpeg.exe",
        ffprobe=tmp_path / "ffprobe.exe",
        version="test",
    )


def test_preflight_gpu_semaphore_serializes_concurrent_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = threading.Lock()
    active = 0
    peak = 0
    first_inside = threading.Event()
    second_started = threading.Event()
    second_inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def fake_run_streaming(
        _ffmpeg: Path,
        args: list[str],
        _on_stdout: Any,
        _on_stderr: Any,
        _cancel: threading.Event | None = None,
        _force: threading.Event | None = None,
    ) -> int:
        nonlocal active, peak
        name = threading.current_thread().name
        with guard:
            active += 1
            peak = max(peak, active)
        if name == "preflight-1":
            first_inside.set()
        else:
            second_inside.set()
        assert release.wait(10)
        Path(args[-1]).write_bytes(b"preflight")
        with guard:
            active -= 1
        return 0

    monkeypatch.setattr(preflight, "run_streaming", fake_run_streaming)
    paths = _preflight_paths(tmp_path)
    plan = PreflightPlan(normalize_audio=True, cap_bitrate=False)

    def worker(src: Path) -> None:
        if threading.current_thread().name == "preflight-2":
            second_started.set()
        try:
            run_preflight(src, plan, paths, lambda _event: None)
        except BaseException as exc:  # noqa: BLE001 - asserted in the main thread
            errors.append(exc)

    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    t1 = threading.Thread(target=worker, args=(first,), name="preflight-1")
    t2 = threading.Thread(target=worker, args=(second,), name="preflight-2")

    t1.start()
    assert first_inside.wait(5)
    t2.start()
    assert second_started.wait(5)
    # The first pass holds the semaphore, so the second must not enter ffmpeg.
    assert not second_inside.wait(0.2)
    release.set()
    for thread in (t1, t2):
        thread.join(10)
        assert not thread.is_alive()

    assert not errors
    assert peak == 1
    assert preflight._PREFLIGHT_GPU_SEM.acquire(blocking=False)
    preflight._PREFLIGHT_GPU_SEM.release()


def test_preflight_gpu_semaphore_released_after_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _preflight_paths(tmp_path)
    plan = PreflightPlan(normalize_audio=True, cap_bitrate=False)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    def ok(
        _ffmpeg: Path,
        args: list[str],
        _on_stdout: Any,
        _on_stderr: Any,
        _cancel: threading.Event | None = None,
        _force: threading.Event | None = None,
    ) -> int:
        Path(args[-1]).write_bytes(b"preflight")
        return 0

    monkeypatch.setattr(preflight, "run_streaming", ok)
    run_preflight(src, plan, paths, lambda _event: None)
    assert preflight._PREFLIGHT_GPU_SEM.acquire(blocking=False)
    preflight._PREFLIGHT_GPU_SEM.release()

    def boom(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(preflight, "run_streaming", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        run_preflight(src, plan, paths, lambda _event: None)
    assert preflight._PREFLIGHT_GPU_SEM.acquire(blocking=False)
    preflight._PREFLIGHT_GPU_SEM.release()


def test_preflight_cancel_while_gpu_busy_does_not_run_ffmpeg(tmp_path: Path) -> None:
    paths = _preflight_paths(tmp_path)
    plan = PreflightPlan(normalize_audio=True, cap_bitrate=False)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    cancel = threading.Event()
    cancel.set()
    attempted = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        attempted.set()
        try:
            run_preflight(src, plan, paths, lambda _event: None, cancel)
        except BaseException as exc:  # noqa: BLE001 - asserted in the main thread
            errors.append(exc)

    assert preflight._PREFLIGHT_GPU_SEM.acquire(blocking=False)
    try:
        thread = threading.Thread(target=worker, name="preflight-cancel")
        thread.start()
        assert attempted.wait(5)
        thread.join(5)
        assert not thread.is_alive()
    finally:
        preflight._PREFLIGHT_GPU_SEM.release()

    assert len(errors) == 1
    assert isinstance(errors[0], PatchCancelledError)
    assert not list(tmp_path.glob("*.preflight-*"))
    assert preflight._PREFLIGHT_GPU_SEM.acquire(blocking=False)
    preflight._PREFLIGHT_GPU_SEM.release()


# ---------- stage 2: parallel batch ----------


def test_two_sources_patch_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(2, timeout=5)
    guard = threading.Lock()
    entered = 0
    completed = 0

    def fake_patch(req: PatchRequest, *_args: Any) -> SimpleNamespace:
        nonlocal entered, completed
        with guard:
            entered += 1
        barrier.wait()  # both workers must be inside patch() together
        with guard:
            completed += 1
        return _fake_result(req, tmp_path)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path)
    first = _mk(tmp_path, "a.mp4")
    second = _mk(tmp_path, "b.mp4")
    _select(ctrl, [first, second])

    ctrl.start_patch(60000, "direct-atom")
    done = _done(_run_to_done(ctrl))

    assert entered == 2
    assert completed == 2
    assert len(done.batch_results) == 2
    assert done.failed == []
    assert done.cancelled is False


def test_progress_is_monotonic_across_concurrent_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    later_file_progressed = threading.Event()

    def fake_patch(
        req: PatchRequest, _ff: Any, emit: Any, _cancel: threading.Event
    ) -> SimpleNamespace:
        if req.src.name == "b.mp4":
            emit(ProgressEvent(1.0))  # file 2 of 2: overall jumps to 1.0
            later_file_progressed.set()
        else:
            assert later_file_progressed.wait(5)
            emit(ProgressEvent(0.1))  # file 1 would move overall back to 0.05
        return _fake_result(req, tmp_path)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path)
    _select(ctrl, [_mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")])

    ctrl.start_patch(60000, "direct-atom")
    events = _run_to_done(ctrl)
    done = _done(events)
    assert len(done.batch_results) == 2

    fractions = [e.fraction for e in events if isinstance(e, ProgressEvent)]
    assert fractions
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert all(e.total_files == 2 for e in events if isinstance(e, ProgressEvent))


def test_single_file_batch_still_returns_one_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[PatchRequest] = []

    def fake_patch(req: PatchRequest, *_args: Any) -> SimpleNamespace:
        requests.append(req)
        return _fake_result(req, tmp_path)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path)
    clip = _mk(tmp_path, "only.mp4")
    _select(ctrl, [clip])

    ctrl.start_patch(60000, "direct-atom")
    done = _done(_run_to_done(ctrl))

    assert len(requests) == 1
    assert len(done.batch_results) == 1
    assert done.total_files == 1
    assert done.failed == []


def test_fan_out_targets_run_sequentially_inside_one_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = threading.Lock()
    active = 0
    peak = 0
    requests: list[PatchRequest] = []
    thread_names: list[str] = []

    def fake_patch(req: PatchRequest, *_args: Any) -> SimpleNamespace:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            requests.append(req)
            thread_names.append(threading.current_thread().name)
        with guard:
            active -= 1
        return _fake_result(req, tmp_path)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path, export_platforms=["tiktok", "youtube"])
    _select(ctrl, [_mk(tmp_path, "fanout.mp4")])

    ctrl.start_patch(60000, "direct-atom")
    done = _done(_run_to_done(ctrl))

    assert [req.platform_profile for req in requests] == ["tiktok", "youtube"]
    assert len(done.batch_results) == 2
    assert done.total_files == 1
    assert peak == 1
    assert len(set(thread_names)) == 1


def test_cancel_while_patch_blocked_reports_cancelled_without_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()

    def fake_patch(
        _req: PatchRequest, _ff: Any, _emit: Any, cancel: threading.Event
    ) -> SimpleNamespace:
        started.set()
        assert release.wait(10)
        if cancel.is_set():
            raise PatchCancelledError("cancelled")
        return SimpleNamespace(output=tmp_path / "late.mp4", experimental=False, after=None)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path)
    _select(ctrl, [_mk(tmp_path, "blocked.mp4")])

    ctrl.start_patch(60000, "direct-atom")
    assert started.wait(5)

    ctrl.cancel()
    begin = time.monotonic()
    ctrl.shutdown(timeout=0.2)
    assert time.monotonic() - begin < 2.0

    # A blocked worker may outlive shutdown(timeout); it must not block the
    # batch from reporting cancellation once the patch returns.
    release.set()
    worker = ctrl._worker
    assert worker is not None
    worker.join(5)
    assert not worker.is_alive()

    seen: list[object] = []
    ctrl.drain(seen.append, limit=100_000)
    done = _done(seen)
    assert done.cancelled is True
    assert ctrl._executor is None
    assert not ctrl.active_patching_paths


def test_stop_on_error_keeps_one_source_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[PatchRequest] = []
    lock = threading.Lock()
    second_started = threading.Event()

    def fake_patch(req: PatchRequest, *_args: Any) -> SimpleNamespace:
        with lock:
            calls.append(req)
        if req.src.name == "a.mp4":
            raise RuntimeError("boom")
        second_started.set()
        return _fake_result(req, tmp_path)

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    ctrl = _controller(tmp_path, stop_on_error=True)
    _select(ctrl, [_mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")])

    ctrl.start_patch(60000, "direct-atom")
    done = _done(_run_to_done(ctrl))

    assert [req.src.name for req in calls] == ["a.mp4"]
    assert not second_started.is_set()
    assert done.cancelled is False
    assert len(done.failed) == 1
    assert done.failed[0][0].name == "a.mp4"
