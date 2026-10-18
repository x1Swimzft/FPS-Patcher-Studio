"""Thin subprocess wrappers for ffprobe (JSON) and ffmpeg (streaming)."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any

from .errors import PatchCancelledError, ProbeError
from .ffmpeg_locator import CREATE_NO_WINDOW

LineCallback = Callable[[str], None]


def run_json(ffprobe: Path, args: Sequence[str], timeout: float = 30) -> dict[str, Any]:
    """Run ffprobe with JSON output and return parsed dict."""
    cmd = [str(ffprobe), "-v", "error", "-print_format", "json", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"ffprobe failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise ProbeError(proc.stderr.strip() or f"ffprobe exited with {proc.returncode}")
    try:
        data: dict[str, Any] = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError(f"Invalid ffprobe JSON: {exc}") from exc
    return data


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
    cmd = [str(ffmpeg), *args]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    assert proc.stdout is not None and proc.stderr is not None
    readers = [
        threading.Thread(target=_pump, args=(proc.stdout, on_stdout), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, on_stderr), daemon=True),
    ]
    for t in readers:
        t.start()
    while True:
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            proc.wait()
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
