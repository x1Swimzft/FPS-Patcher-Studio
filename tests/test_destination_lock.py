"""Per-destination serialization: threads, processes, and real patch jobs."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from fps_patcher.core.errors import OutputFileExistsError, PatchCancelledError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import PatchRequest
from fps_patcher.core.patcher import (
    _DEST_LOCKS,
    _destination_key,
    _DestinationLock,
    output_base_for,
    output_path_for,
    patch,
)
from fps_patcher.core.prober import probe


def test_destination_lock_serializes_threads(tmp_path: Path) -> None:
    final = tmp_path / "clip_ts60000.mp4"
    active = 0
    peak = 0
    guard = threading.Lock()
    start = threading.Barrier(4)

    def worker() -> None:
        nonlocal active, peak
        start.wait()
        lock = _DestinationLock(final)
        lock.acquire()
        try:
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
        finally:
            with guard:
                active -= 1
            lock.release()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()

    assert peak == 1


def test_destination_lock_wait_is_cancellable(tmp_path: Path) -> None:
    final = tmp_path / "clip_ts60000.mp4"
    holder = _DestinationLock(final)
    holder.acquire()
    cancel = threading.Event()
    errors: list[BaseException] = []
    started = time.monotonic()

    def waiter() -> None:
        time.sleep(0.05)
        cancel.set()
        try:
            _DestinationLock(final).acquire(cancel)
        except BaseException as exc:  # noqa: BLE001 - assert in the main thread
            errors.append(exc)

    thread = threading.Thread(target=waiter)
    try:
        thread.start()
        thread.join(5)
        assert not thread.is_alive()
        assert time.monotonic() - started < 5
        assert len(errors) == 1
        assert isinstance(errors[0], PatchCancelledError)
    finally:
        holder.release()
        thread.join(5)


def test_destination_key_is_case_insensitive_on_windows(tmp_path: Path) -> None:
    upper = tmp_path / "CLIP.MP4"
    lower = tmp_path / "clip.mp4"
    if os.name == "nt":
        assert _destination_key(upper) == _destination_key(lower)
    else:
        assert _destination_key(upper) != _destination_key(lower)


@pytest.mark.skipif(os.name != "nt", reason="named mutex is Windows-only")
def test_named_mutex_blocks_another_process(tmp_path: Path) -> None:
    from fps_patcher.core.win_job import NamedMutex

    name = f"Local\\fps-patcher-test-{os.getpid()}-{time.time_ns()}"
    flag = tmp_path / "acquired.flag"
    script = tmp_path / "take_mutex.py"
    script.write_text(
        "import sys, time\n"
        "from fps_patcher.core.win_job import NamedMutex\n"
        "m = NamedMutex(sys.argv[1])\n"
        "m.acquire()\n"
        "open(sys.argv[2], 'w').write('1')\n"
        "time.sleep(0.1)\n"
        "m.close()\n",
        encoding="utf-8",
    )

    mutex = NamedMutex(name)
    assert mutex.acquire()
    proc = subprocess.Popen([sys.executable, str(script), name, str(flag)])
    try:
        time.sleep(0.4)
        assert not flag.exists()  # child is blocked on the same name
        mutex.release()
        assert proc.wait(timeout=5) == 0
        assert flag.exists()
    finally:
        mutex.close()
        proc.kill()
        proc.wait(timeout=5)


def test_concurrent_patches_to_one_destination_do_not_overlap_replace(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    req = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        overwrite=True,
    )
    final = output_path_for(req)
    active = 0
    peak = 0
    guard = threading.Lock()
    real_replace = os.replace

    def tracked_replace(src: object, dst: object) -> None:
        nonlocal active, peak
        if str(dst) == str(final):
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
        try:
            real_replace(src, dst)  # type: ignore[arg-type]
        finally:
            if str(dst) == str(final):
                with guard:
                    active -= 1

    monkeypatch.setattr(os, "replace", tracked_replace)
    results = []
    errors: list[BaseException] = []

    def job() -> None:
        try:
            results.append(patch(req, ff, lambda _evt: None))
        except BaseException as exc:  # noqa: BLE001 - surface in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=job) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
        assert not thread.is_alive()

    assert not errors
    assert len(results) == 2
    assert peak == 1  # replace calls to the same destination were serialized
    assert final.is_file()
    assert probe(final, ff.ffprobe).timescale == 60000
    assert not list(tmp_path.glob("*.part"))


def _race_two_patches(
    clip30: Path,
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    auto_rename: bool,
) -> tuple[Path, list[object], list[BaseException]]:

    req = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        overwrite=False,
        auto_rename=auto_rename,
    )
    base = output_base_for(req)
    first_replace = threading.Event()
    release_first = threading.Event()
    second_waiting = threading.Event()
    real_replace = os.replace
    real_acquire = _DestinationLock.acquire
    threads: dict[str, threading.Thread] = {}

    def tracked_acquire(
        self: _DestinationLock, cancel_event: threading.Event | None = None
    ) -> None:
        if threading.current_thread() is threads.get("second"):
            second_waiting.set()
        real_acquire(self, cancel_event)

    def slow_replace(src: object, dst: object) -> None:
        if str(dst) == str(base) and threading.current_thread() is threads.get("first"):
            first_replace.set()
            assert release_first.wait(10)
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", slow_replace)
    monkeypatch.setattr(_DestinationLock, "acquire", tracked_acquire)
    results: list[object] = []
    errors: list[BaseException] = []

    def job() -> None:
        try:
            results.append(patch(req, ff, lambda _evt: None))
        except BaseException as exc:  # noqa: BLE001 - surface in the main thread
            errors.append(exc)

    threads["first"] = threading.Thread(target=job)
    threads["second"] = threading.Thread(target=job)
    threads["first"].start()
    assert first_replace.wait(10)
    threads["second"].start()
    assert second_waiting.wait(10)
    release_first.set()
    for thread in threads.values():
        thread.join(60)
        assert not thread.is_alive()
    return base, results, errors


def test_concurrent_patches_auto_rename_pick_distinct_outputs(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, results, errors = _race_two_patches(
        clip30, ff, tmp_path, monkeypatch, auto_rename=True
    )

    assert not errors
    assert len(results) == 2
    assert base.is_file()
    assert base.with_name(f"{base.stem} (1){base.suffix}").is_file()
    assert not list(tmp_path.glob("*.part"))


def test_concurrent_patches_auto_rename_off_fails_second(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, results, errors = _race_two_patches(
        clip30, ff, tmp_path, monkeypatch, auto_rename=False
    )

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], OutputFileExistsError)
    assert base.is_file()
    assert not list(tmp_path.glob("*.part"))


def test_repeated_patches_reuse_one_lock_and_leave_no_temps(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path
) -> None:
    req = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        overwrite=True,
    )
    base = output_base_for(req)
    locks_before = len(_DEST_LOCKS)

    for _ in range(3):
        result = patch(req, ff, lambda _evt: None)
        assert result.output == base
        assert probe(base, ff.ffprobe).timescale == 60000
        assert not list(tmp_path.glob("*.part"))
        assert not list(tmp_path.glob("*.preflight*"))

    # One lock entry for one destination, not one per job.
    assert len(_DEST_LOCKS) == locks_before + 1
