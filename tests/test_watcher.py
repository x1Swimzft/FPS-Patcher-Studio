"""Phase 2 (v0.7.0): stdlib polling watch folder."""

from __future__ import annotations

import os
from pathlib import Path

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
    watcher._is_locked = lambda _path: True  # type: ignore[assignment]

    watcher.scan(now=0.0)
    assert watcher.scan(now=1.0) == []
    watcher._is_locked = lambda _path: False  # type: ignore[assignment]
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
