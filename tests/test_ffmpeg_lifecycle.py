"""Windows process-tree lifecycle: Job Object kills ffmpeg descendants."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

from fps_patcher.core.errors import PatchCancelledError, ProbeError
from fps_patcher.core.ffmpeg_runner import run_json, run_streaming
from fps_patcher.core.win_job import ProcessJob

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects only")


def _pid_alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait_pid_gone(pid: int, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


def _kill_pid(pid: int) -> None:
    if _pid_alive(pid):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )


_PARENT = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(str(child.pid))
time.sleep(60)
"""

_GRANDCHILD_RUNNER = """
import sys
from pathlib import Path
from fps_patcher.core.ffmpeg_runner import run_streaming
run_streaming(
    Path(sys.executable),
    ["-c", sys.argv[2], sys.argv[1]],
    lambda _l: None,
    lambda _l: None,
)
"""


def _read_pid(path: Path, timeout: float = 10.0) -> int:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"pid file was not written: {path}")


def test_job_object_is_active() -> None:
    job = ProcessJob()
    try:
        assert job.active
    finally:
        job.close()


def test_cancel_kills_descendants(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    pid: int | None = None
    cancel = threading.Event()

    def cancel_when_spawned() -> None:
        _read_pid(pid_file)
        cancel.set()

    threading.Thread(target=cancel_when_spawned, daemon=True).start()
    try:
        with pytest.raises(PatchCancelledError):
            run_streaming(
                Path(sys.executable),
                ["-c", _PARENT, str(pid_file)],
                lambda _line: None,
                lambda _line: None,
                cancel,
            )
        pid = _read_pid(pid_file, timeout=2)
        assert _wait_pid_gone(pid)
    finally:
        if pid is not None:
            _kill_pid(pid)


def test_hard_kill_of_parent_reaps_descendants(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    runner = tmp_path / "runner.py"
    runner.write_text(_GRANDCHILD_RUNNER, encoding="utf-8")
    pid: int | None = None
    proc = subprocess.Popen([sys.executable, str(runner), str(pid_file), _PARENT])
    try:
        pid = _read_pid(pid_file)
        assert _pid_alive(pid)
        proc.kill()
        proc.wait(timeout=5)
        assert _wait_pid_gone(pid)
    finally:
        proc.kill()
        proc.wait(timeout=5)
        if pid is not None:
            _kill_pid(pid)


_SELF_PID = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"


def test_empty_job_terminate_returns_false() -> None:
    job = ProcessJob()
    try:
        assert not job.terminate()
    finally:
        job.close()


def test_cancel_falls_back_when_job_assignment_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ProcessJob, "assign", lambda self, proc: False)
    pid_file = tmp_path / "self.pid"
    cancel = threading.Event()

    def cancel_when_spawned() -> None:
        _read_pid(pid_file)
        cancel.set()

    threading.Thread(target=cancel_when_spawned, daemon=True).start()
    pid: int | None = None
    started = time.monotonic()
    try:
        with pytest.raises(PatchCancelledError):
            run_streaming(
                Path(sys.executable),
                ["-c", _SELF_PID, str(pid_file)],
                lambda _line: None,
                lambda _line: None,
                cancel,
            )
        assert time.monotonic() - started < 5
        pid = _read_pid(pid_file, timeout=2)
        assert _wait_pid_gone(pid)
    finally:
        if pid is not None:
            _kill_pid(pid)


def test_run_json_timeout_kills_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = subprocess.Popen
    pid_file = tmp_path / "ffprobe.pid"

    def fake_popen(cmd: object, **kwargs: Any) -> subprocess.Popen[str]:
        return cast(
            "subprocess.Popen[str]",
            real_popen([sys.executable, "-c", _SELF_PID, str(pid_file)], **kwargs),
        )

    monkeypatch.setattr("fps_patcher.core.ffmpeg_runner.subprocess.Popen", fake_popen)
    with pytest.raises(ProbeError, match="timed out"):
        run_json(Path(sys.executable), [], timeout=0.2)
    pid = _read_pid(pid_file, timeout=2)
    try:
        assert _wait_pid_gone(pid)
    finally:
        _kill_pid(pid)
