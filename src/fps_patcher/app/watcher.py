"""Stdlib-only watch folder intake. No watchdog, no Tk, no third-party deps.

A file is ready when its size and mtime stay unchanged for ``settle_scans`` scans,
it is older than ``min_age_s``, it opens for read/write on Windows, and it is not
one of our own outputs. Files already in the folder when watching starts are
recorded and ignored, so pointing the watcher at an old export folder does not
patch its backlog. The callback runs on the watcher thread; it must be
thread-safe and quick (the UI pushes into a queue).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core.models import SUPPORTED_EXTENSIONS

log = logging.getLogger("fps_patcher.watcher")

_OWN_OUTPUT_RE = re.compile(r"_ts\d+( \(\d+\))?$", re.IGNORECASE)
_TEMP_SUFFIXES = (".tmp", ".part", ".crdownload", ".preflight")


@dataclass
class _Pending:
    size: int
    mtime_ns: int
    first_seen: float
    stable: int = 0


def _is_locked(path: Path) -> bool:
    """Windows: a file another process holds exclusively cannot be opened O_RDWR."""
    if os.name != "nt":
        return False
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return True
    else:
        os.close(fd)
        return False


class FolderWatcher:
    """Poll a folder and call ``on_ready`` once per completed export."""

    def __init__(
        self,
        folder: Path,
        on_ready: Callable[[Path], None],
        *,
        poll_interval: float = 1.0,
        settle_scans: int = 2,
        min_age_s: float = 1.0,
    ) -> None:
        self.folder = Path(folder)
        self.on_ready = on_ready
        self.poll_interval = max(0.1, poll_interval)
        self.settle_scans = max(1, settle_scans)
        self.min_age_s = max(0.0, min_age_s)
        self._pending: dict[Path, _Pending] = {}
        self._processed: dict[Path, tuple[int, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._primed = False
        self._deliver_lock = threading.RLock()
        self._is_locked = _is_locked

    @staticmethod
    def is_own_output(path: Path) -> bool:
        name = path.name.lower()
        if name.startswith(".") or name.startswith("~$"):
            return True
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return True
        if _OWN_OUTPUT_RE.search(path.stem):
            return True
        if ".preflight" in name or ".colr" in name:
            return True
        return name.endswith(_TEMP_SUFFIXES)

    def scan(self, now: float | None = None) -> list[Path]:
        """One deterministic poll. Returns files that became ready this scan."""
        moment = time.monotonic() if now is None else now
        ready: list[Path] = []
        try:
            entries = list(os.scandir(self.folder))
        except OSError:
            return ready

        seen: set[Path] = set()
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = Path(entry.path)
            if self.is_own_output(path):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            seen.add(path)

            # Already emitted with the same signature: no pending bookkeeping
            # and, importantly, no network O_RDWR probe on every later scan.
            signature = (stat.st_size, stat.st_mtime_ns)
            if self._processed.get(path) == signature:
                self._pending.pop(path, None)
                continue

            pending = self._pending.get(path)
            if (
                pending is None
                or pending.size != stat.st_size
                or pending.mtime_ns != stat.st_mtime_ns
            ):
                self._pending[path] = _Pending(
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    first_seen=moment,
                )
                continue

            pending.stable += 1
            if pending.stable < self.settle_scans - 1:
                continue
            if moment - pending.first_seen < self.min_age_s:
                continue
            if self._is_locked(path):
                continue

            with self._deliver_lock:
                if self._stop.is_set():
                    continue  # a replacement watcher will rediscover the file
                self._processed[path] = signature
                self._pending.pop(path, None)
                ready.append(path)
                try:
                    self.on_ready(path)
                except Exception:
                    log.exception("Watch callback failed for %s", path)

        # Drop state for files that vanished; keeps long-running watchers bounded.
        for path in list(self._pending):
            if path not in seen:
                self._pending.pop(path, None)
        for path in list(self._processed):
            if path not in seen:
                self._processed.pop(path, None)
        return ready

    def prime(self) -> None:
        """Ignore files that already exist; only files that change later are delivered."""
        try:
            entries = list(os.scandir(self.folder))
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat()
                    self._processed[Path(entry.path)] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # A fresh event per run: a non-blocking stop followed by start must not
        # revive the old thread by clearing the event it is waiting on.
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(self._stop,), name="fps-folder-watcher", daemon=True
        )
        self._thread.start()

    def _run(self, stop: threading.Event) -> None:
        # Prime on the poll thread: folder I/O never blocks the UI thread.
        if not self._primed:
            self._primed = True
            self.prime()
        while not stop.wait(self.poll_interval):
            try:
                self.scan()
            except Exception:
                log.exception("Watch scan failed")

    def stop(self, timeout: float = 3.0, *, wait: bool = True) -> None:
        """Signal the poll loop to exit. ``wait=False`` never blocks the caller.

        The callback only pushes into a thread-safe queue, so a scan already in
        flight may finish after a non-blocking stop without touching Tk.
        """
        self._stop.set()
        # Wait only for an in-flight callback (queue.put), never for a scan.
        with self._deliver_lock:
            pass
        thread = self._thread
        self._thread = None
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def __enter__(self) -> FolderWatcher:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
