"""Thin subprocess wrappers for ffprobe (JSON) and ffmpeg (streaming)."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any

from .errors import PatchCancelledError, PatchError, ProbeError
from .ffmpeg_locator import CREATE_NO_WINDOW
from .win_job import ProcessJob

LineCallback = Callable[[str], None]

_RESERVED_EXTRA_ARGS = frozenset({"-i", "-y", "-n"})


def parse_extra_ffmpeg_args(text: str) -> list[str]:
    """Split a user argument string into argv tokens without invoking a shell.

    ``shlex`` only tokenises; the result always goes to ``subprocess`` as a list,
    so quotes, ``&`` or ``|`` cannot become shell syntax. A malformed quote or a
    NUL byte is rejected instead of silently dropping part of the input. Options
    that would replace the app's input or output (``-i``, ``-y``, ``-n``) are
    rejected before FFmpeg runs.
    """
    if not text or not text.strip():
        return []
    if "\x00" in text:
        raise PatchError("Extra FFmpeg arguments contain a NUL byte.")
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as exc:
        raise PatchError(f"Invalid extra FFmpeg arguments: {exc}") from exc
    reserved = sorted(
        token
        for token in set(tokens)
        if token in _RESERVED_EXTRA_ARGS or token.startswith("-i=")
    )
    if reserved:
        raise PatchError(
            "Extra FFmpeg arguments may not override the app's input/output: "
            + ", ".join(reserved)
        )
    return tokens


def _checked_exe(path: Path) -> str:
    """Return the executable path as str, rejecting anything that is not an existing file."""
    if not path.is_file():
        raise ProbeError(f"Executable not found: {path}")
    return str(path)


def _kill(proc: subprocess.Popen[str]) -> None:
    with contextlib.suppress(OSError):
        proc.kill()


_CANCEL_GRACE_S = 5.0


def _force_kill_tree(job: ProcessJob, proc: subprocess.Popen[str]) -> None:
    """Second Ctrl+C / grace timeout: job kill then a native tree kill fallback."""
    job.terminate()
    if proc.poll() is None and os.name == "nt" and proc.pid:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
    _kill(proc)


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
    force_event: threading.Event | None = None,
) -> int:
    """Run ffmpeg, streaming stdout/stderr lines to callbacks. Returns exit code.

    The first cancel asks the job/child to stop and waits briefly. If the
    process is still alive when ``force_event`` is set (second Ctrl+C) or the
    grace period expires, its process tree is force-killed before raising.
    """
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
        cancelled = False
        cancel_deadline = 0.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                if not cancelled:
                    cancelled = True
                    if not job.terminate():  # no job/assignment: direct child only
                        _kill(proc)
                    cancel_deadline = time.monotonic() + _CANCEL_GRACE_S
                forced = force_event is not None and force_event.is_set()
                if forced or time.monotonic() >= cancel_deadline:
                    if proc.poll() is None:
                        _force_kill_tree(job, proc)
                    break
            try:
                code = proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        for t in readers:
            t.join(timeout=2)
        if cancelled:
            raise PatchCancelledError("Patch cancelled by user.")
        return code
    finally:
        job.close()
