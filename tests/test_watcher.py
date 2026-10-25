"""Phase 2 (v0.7.0): stdlib polling watch folder."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, cast

from fps_patcher.app.watcher import FolderWatcher


def _touch(folder: Path, name: str, data: bytes = b"x") -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def test_own_output_filter() -> None:
    assert FolderWatcher.is_own_output(Path("clip_ts60000.mp4"))
    assert FolderWatcher.is_own_output(Path("clip_ts60000 (1).mp4"))
    assert FolderWatcher.is_own_output(Path("clip.preflight.mp4"))
    assert FolderWatcher.is_own_output(Path("clip.colr.tmp"))
    assert FolderWatcher.is_own_output(Path(".hidden.mp4"))
    assert FolderWatcher.is_own_output(Path("~$clip.mp4"))
    assert FolderWatcher.is_own_output(Path("clip.txt"))
    assert not FolderWatcher.is_own_output(Path("clip.mp4"))


def test_ready_after_settle_and_only_once(tmp_path: Path) -> None:
    clip = _touch(tmp_path, "clip.mp4")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=2, min_age_s=0.0)

    assert watcher.scan(now=0.0) == []
    assert watcher.scan(now=10.0) == [clip]
    assert watcher.scan(now=20.0) == []
    assert seen == [clip]


def test_growing_file_is_held_back(tmp_path: Path) -> None:
    clip = _touch(tmp_path, "clip.mp4", b"a")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=2, min_age_s=10.0)

    watcher.scan(now=0.0)
    clip.write_bytes(b"ab")
    assert watcher.scan(now=1.0) == []
    assert watcher.scan(now=6.0) == []
    assert watcher.scan(now=12.0) == [clip]


def test_locked_file_is_held_until_released(tmp_path: Path) -> None:
    clip = _touch(tmp_path, "clip.mp4")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=2, min_age_s=0.0)
    watcher._is_locked = lambda path: True

    watcher.scan(now=0.0)
    assert watcher.scan(now=1.0) == []
    watcher._is_locked = lambda path: False
    assert watcher.scan(now=2.0) == [clip]


def test_own_outputs_are_ignored(tmp_path: Path) -> None:
    keep = _touch(tmp_path, "keep.mp4")
    _touch(tmp_path, "keep_ts60000.mp4")
    _touch(tmp_path, "keep.preflight.mp4")
    _touch(tmp_path, "keep.colr.tmp")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=2, min_age_s=0.0)

    watcher.scan(now=0.0)
    assert watcher.scan(now=1.0) == [keep]


def test_processed_file_skips_lock_probe_on_later_scans(tmp_path: Path) -> None:
    _touch(tmp_path, "clip.mp4")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=2, min_age_s=0.0)
    watcher.scan(now=0.0)
    assert watcher.scan(now=1.0) == [tmp_path / "clip.mp4"]

    probes: list[Path] = []

    def locked(path: Path) -> bool:
        probes.append(path)
        return False

    watcher._is_locked = locked
    assert watcher.scan(now=2.0) == []
    assert probes == []


def test_vanished_file_is_forgotten(tmp_path: Path) -> None:
    clip = _touch(tmp_path, "clip.mp4")
    watcher = FolderWatcher(tmp_path, lambda _p: None, settle_scans=2, min_age_s=0.0)

    watcher.scan(now=0.0)
    os.remove(clip)
    watcher.scan(now=1.0)
    assert watcher._pending == {}


def test_callback_failure_does_not_stop_the_scan(tmp_path: Path) -> None:
    clip = _touch(tmp_path, "clip.mp4")

    def boom(_path: Path) -> None:
        raise RuntimeError("consumer failed")

    watcher = FolderWatcher(tmp_path, boom, settle_scans=2, min_age_s=0.0)
    watcher.scan(now=0.0)
    assert watcher.scan(now=1.0) == [clip]


def test_thread_lifecycle_is_idempotent(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, lambda _p: None, poll_interval=0.05, min_age_s=0.0)
    watcher.start()
    watcher.start()
    watcher.stop()
    watcher.stop()


def test_nonblocking_stop_does_not_wait_for_slow_scan(tmp_path: Path) -> None:
    """Simulates a network share: scandir is stuck while the UI closes."""
    watcher = FolderWatcher(tmp_path, lambda _p: None, poll_interval=0.01, min_age_s=0.0)
    entered = threading.Event()
    release = threading.Event()

    def slow_scan(now: float | None = None) -> list[Path]:
        entered.set()
        assert release.wait(5)
        return []

    watcher.scan = slow_scan  # type: ignore[method-assign]
    watcher.start()
    assert entered.wait(2)
    thread = watcher._thread
    assert thread is not None

    started = time.perf_counter()
    watcher.stop(wait=False)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2
    assert thread.is_alive()
    release.set()
    thread.join(2)
    assert not thread.is_alive()


def test_restart_after_nonblocking_stop_retires_old_thread(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, lambda _p: None, poll_interval=0.01, min_age_s=0.0)
    entered = threading.Event()
    release = threading.Event()

    def slow_scan(now: float | None = None) -> list[Path]:
        entered.set()
        assert release.wait(5)
        return []

    watcher.scan = slow_scan  # type: ignore[method-assign]
    watcher.start()
    assert entered.wait(2)
    first = watcher._thread
    assert first is not None

    watcher.stop(wait=False)
    watcher.start()
    second = watcher._thread
    assert second is not None and second is not first

    release.set()
    first.join(2)
    assert not first.is_alive()  # the old stop event was not cleared by start()
    watcher.stop()


def test_prime_ignores_files_that_already_exist(tmp_path: Path) -> None:
    old = _touch(tmp_path, "old.mp4")
    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=1, min_age_s=0.0)
    watcher._is_locked = cast(Any, lambda _path: False)

    watcher.prime()
    assert watcher.scan(now=0.0) == []
    assert watcher.scan(now=1.0) == []

    old.write_bytes(b"xx")  # changing after start makes it a new export again
    assert watcher.scan(now=2.0) == []
    assert watcher.scan(now=3.0) == [old]
    assert seen == [old]


def test_start_ignores_backlog_and_delivers_new_files(tmp_path: Path) -> None:
    old = _touch(tmp_path, "old.mp4")
    seen: list[Path] = []
    watcher = FolderWatcher(
        tmp_path, seen.append, poll_interval=0.01, settle_scans=1, min_age_s=0.0
    )
    watcher._is_locked = cast(Any, lambda _path: False)
    watcher.start()
    try:
        deadline = time.time() + 2
        while not watcher._processed and time.time() < deadline:
            time.sleep(0.01)
        assert watcher._processed, "prime ran on the poll thread"
        new = _touch(tmp_path, "new.mp4")
        deadline = time.time() + 2
        while not seen and time.time() < deadline:
            time.sleep(0.01)
    finally:
        watcher.stop()
    assert seen == [new]
    assert old not in seen


def test_restart_delivers_files_that_arrived_while_stopped(tmp_path: Path) -> None:
    seen: list[Path] = []
    watcher = FolderWatcher(
        tmp_path, seen.append, poll_interval=0.01, settle_scans=1, min_age_s=0.0
    )
    watcher._is_locked = cast(Any, lambda _path: False)
    watcher.start()
    deadline = time.time() + 2
    while not watcher._primed and time.time() < deadline:
        time.sleep(0.01)
    watcher.stop()

    clip = _touch(tmp_path, "while-paused.mp4")
    watcher.start()
    try:
        deadline = time.time() + 2
        while not seen and time.time() < deadline:
            time.sleep(0.01)
    finally:
        watcher.stop()
    assert seen == [clip]
