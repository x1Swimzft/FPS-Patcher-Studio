"""Thin subprocess wrappers for ffprobe (JSON) and ffmpeg (streaming)."""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any

from .errors import PatchCancelledError, ProbeError
from .ffmpeg_locator import CREATE_NO_WINDOW
from .win_job import ProcessJob

LineCallback = Callable[[str], None]


def _checked_exe(path: Path) -> str:
    """Return the executable path as str, rejecting anything that is not an existing file."""
    if not path.is_file():
        raise ProbeError(f"Executable not found: {path}")
    return str(path)


def _kill(proc: subprocess.Popen[str]) -> None:
    with contextlib.suppress(OSError):
        proc.kill()


def _wait_bounded(proc: subprocess.Popen[str], timeout: float = 5.0) -> None:
    """Wait for a killed child, falling back to a direct kill; never wait forever."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=timeout)


def run_json(ffprobe: Path, args: Sequence[str], timeout: float = 30) -> dict[str, Any]:
    """Run ffprobe with JSON output and return parsed dict."""
    cmd = [_checked_exe(ffprobe), "-v", "error", "-print_format", "json", *args]
    job = ProcessJob()
    try:
        proc = subprocess.Popen(
            cmd,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        job.close()
        raise ProbeError(f"ffprobe failed to run: {exc}") from exc
    try:
        try:
            job.assign(proc)
        except BaseException:
            _kill(proc)
            raise
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if not job.terminate():
                _kill(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=5)
            raise ProbeError(f"ffprobe timed out after {timeout:g}s") from exc
        if proc.returncode != 0:
            raise ProbeError(stderr.strip() or f"ffprobe exited with {proc.returncode}")
        try:
            data: dict[str, Any] = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ProbeError(f"Invalid ffprobe JSON: {exc}") from exc
        return data
    finally:
        job.close()


def _pump(stream: IO[str], callback: LineCallback) -> None:
    for line in iter(stream.readline, ""):
        line = line.rstrip("\r\n")
        if line:
            callback(line)
    stream.close()


def run_streaming(
    ffmpeg: Path,
    args: Sequence[str],
    on_stdout: LineCallback,
    on_stderr: LineCallback,
    cancel_event: threading.Event | None = None,
) -> int:
    """Run ffmpeg, streaming stdout/stderr lines to callbacks. Returns exit code."""
    cmd = [_checked_exe(ffmpeg), *args]
    job = ProcessJob()
    try:
        proc = subprocess.Popen(
            cmd,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        job.close()
        raise
    try:
        try:
            job.assign(proc)
        except BaseException:
            _kill(proc)
            raise
        assert proc.stdout is not None and proc.stderr is not None
        readers = [
            threading.Thread(target=_pump, args=(proc.stdout, on_stdout), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, on_stderr), daemon=True),
        ]
        for t in readers:
            t.start()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                if not job.terminate():  # no job/assignment: direct child only
                    _kill(proc)
                _wait_bounded(proc)
                for t in readers:
                    t.join(timeout=2)
                raise PatchCancelledError("Patch cancelled by user.")
            try:
                code = proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        for t in readers:
            t.join(timeout=2)
        return code
    finally:
        job.close()
