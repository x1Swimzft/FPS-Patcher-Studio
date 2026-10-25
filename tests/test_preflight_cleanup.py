"""Ownership-marked cleanup for preflight temps (active vs stale vs foreign)."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from fps_patcher.core.preflight import cleanup_stale_preflight, remove_preflight_temp


def _temp(folder: Path, name: str = "clip.preflight-1-abc.mp4", age_s: float = 0) -> Path:
    path = folder / name
    path.write_bytes(b"partial")
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


def _marker(
    temp: Path,
    *,
    pid: int,
    age_s: float,
    tool: str = "fps-patcher-studio",
    temp_name: str | None = None,
    host: str | None = None,
) -> Path:
    marker = temp.with_name(f".{temp.name}.preflight-owner.json")
    marker.write_text(
        json.dumps(
            {
                "tool": tool,
                "host": socket.gethostname() if host is None else host,
                "pid": pid,
                "created": time.time() - age_s,
                "source": "clip.mp4",
                "temp": temp_name if temp_name is not None else temp.name,
            }
        ),
        encoding="utf-8",
    )
    stamp = time.time() - age_s
    os.utime(marker, (stamp, stamp))
    return marker


def test_active_marker_keeps_temp(tmp_path: Path) -> None:
    temp = _temp(tmp_path)
    _marker(temp, pid=os.getpid(), age_s=0)

    assert cleanup_stale_preflight([tmp_path]) == 0
    assert temp.exists()


def test_dead_pid_after_grace_is_removed(tmp_path: Path) -> None:
    temp = _temp(tmp_path, age_s=120)
    marker = _marker(temp, pid=999_999, age_s=120)

    assert cleanup_stale_preflight([tmp_path]) == 1
    assert not temp.exists()
    assert not marker.exists()


def test_young_dead_pid_is_left_for_grace_period(tmp_path: Path) -> None:
    temp = _temp(tmp_path)
    _marker(temp, pid=999_999, age_s=10)

    assert cleanup_stale_preflight([tmp_path]) == 0
    assert temp.exists()


def test_age_cap_removes_even_live_pid(tmp_path: Path) -> None:
    temp = _temp(tmp_path, age_s=24 * 3600 + 1)
    _marker(temp, pid=os.getpid(), age_s=24 * 3600 + 1)

    assert cleanup_stale_preflight([tmp_path]) == 1
    assert not temp.exists()


def test_foreign_or_missing_marker_is_never_touched(tmp_path: Path) -> None:
    foreign = _temp(tmp_path, "foreign.preflight-1-a.mp4")
    _marker(foreign, pid=999_999, age_s=120, tool="other-app")
    unowned = _temp(tmp_path, "unowned.preflight-1-b.mp4")

    assert cleanup_stale_preflight([tmp_path]) == 0
    assert foreign.exists() and unowned.exists()


def test_marker_cannot_point_outside_its_folder(tmp_path: Path) -> None:
    victim = tmp_path.parent / "victim.preflight.mp4"
    victim.write_bytes(b"keep")
    temp = _temp(tmp_path)
    _marker(temp, pid=999_999, age_s=120, temp_name=f"..{os.sep}{victim.name}")
    try:
        assert cleanup_stale_preflight([tmp_path]) == 0
        assert victim.exists()
    finally:
        victim.unlink(missing_ok=True)


def test_marker_from_another_machine_is_never_deleted(tmp_path: Path) -> None:
    temp = _temp(tmp_path, age_s=120)
    _marker(temp, pid=999_999, age_s=120, host="OTHER-PC")

    assert cleanup_stale_preflight([tmp_path]) == 0
    assert temp.exists()


def test_orphan_marker_without_temp_is_removed(tmp_path: Path) -> None:
    temp = _temp(tmp_path, age_s=120)
    marker = _marker(temp, pid=999_999, age_s=120)
    temp.unlink()

    assert cleanup_stale_preflight([tmp_path]) == 1
    assert not marker.exists()


def test_remove_preflight_temp_removes_marker(tmp_path: Path) -> None:
    temp = _temp(tmp_path)
    marker = _marker(temp, pid=os.getpid(), age_s=0)

    remove_preflight_temp(temp)

    assert not temp.exists()
    assert not marker.exists()
