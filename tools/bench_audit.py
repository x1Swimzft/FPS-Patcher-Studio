"""Reproducible measurements for the responsiveness/lifecycle audit.

Run: ``uv run python tools/bench_audit.py``
Stdlib only; writes its fixtures to a temp dir and deletes them on exit.
"""

from __future__ import annotations

import struct
import tempfile
import time
import tracemalloc
from pathlib import Path

from fps_patcher.app.queue_model import InputQueue
from fps_patcher.app.watcher import FolderWatcher
from fps_patcher.core.colr import sanitize
from fps_patcher.ui import thumbnails


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def _full(typ: bytes, payload: bytes = b"") -> bytes:
    return _box(typ, b"\0\0\0\0" + payload)


def _moov(chunk_offset: int) -> bytes:
    entry = _box(b"avc1", b"\0" * 78 + _box(b"colr", b"nclx" + struct.pack(">HHHB", 1, 1, 1, 0)))
    stsd = _full(b"stsd", struct.pack(">I", 1) + entry)
    stco = _full(b"stco", struct.pack(">II", 1, chunk_offset))
    stbl = _box(b"stbl", stsd + stco)
    minf = _box(b"minf", stbl)
    hdlr = _full(b"hdlr", b"\0\0\0\0" + b"vide" + b"\0" * 12)
    trak = _box(b"trak", _box(b"mdia", hdlr + minf))
    meta = _box(b"udta", _box(b"meta", b"\0\0\0\0" + b"editor"))
    return _box(b"moov", trak + meta)


def _make_mp4(path: Path, media_bytes: int) -> None:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    moov = _moov(0)
    offset = len(ftyp) + len(moov) + 8
    moov = _moov(offset)
    with path.open("wb") as fh:
        fh.write(ftyp + moov + struct.pack(">I4s", 8 + media_bytes, b"mdat"))
        chunk = b"\x5a" * (1024 * 1024)
        remaining = media_bytes
        while remaining:
            fh.write(chunk[: min(len(chunk), remaining)])
            remaining -= min(len(chunk), remaining)


def bench_queue(root: Path, count: int = 2000) -> None:
    files = []
    for i in range(count):
        p = root / f"q{i:05d}.mp4"
        p.touch()
        files.append(p)
    q = InputQueue()
    t0 = time.perf_counter()
    result = q.add(files)
    add_s = time.perf_counter() - t0
    for p in files:
        item = q.get(p)
        assert item is not None
        item.selected = True
    t0 = time.perf_counter()
    removed = q.remove_selected()
    remove_s = time.perf_counter() - t0
    print(
        f"queue: add {len(result.added)} files {add_s * 1000:.1f} ms "
        f"({add_s / count * 1e6:.0f} us/file); remove {removed} {remove_s * 1000:.1f} ms"
    )


def bench_watcher(root: Path, count: int = 2000) -> None:
    folder = root / "watch"
    folder.mkdir()
    for i in range(count):
        (folder / f"w{i:05d}.mp4").touch()
    watcher = FolderWatcher(folder, lambda _p: None, settle_scans=2, min_age_s=0)
    t0 = time.perf_counter()
    watcher.scan(now=0.0)
    first_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    ready = watcher.scan(now=1.0)
    second_s = time.perf_counter() - t0
    print(
        f"watcher: {count} files scan1 {first_s * 1000:.1f} ms, "
        f"scan2 {second_s * 1000:.1f} ms, ready {len(ready)}"
    )


def bench_sanitize(root: Path, media_mb: int = 256) -> None:
    path = root / "big.mp4"
    _make_mp4(path, media_mb * 1024 * 1024)
    size_mb = path.stat().st_size / (1024 * 1024)
    tracemalloc.start()
    t0 = time.perf_counter()
    result = sanitize(path)
    elapsed = time.perf_counter() - t0
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"sanitize: {size_mb:.0f} MB in {elapsed:.2f} s "
        f"({size_mb / elapsed:.0f} MB/s), peak python mem {peak / (1024 * 1024):.1f} MB, "
        f"color={result.status}"
    )


def bench_thumb_cache() -> None:
    thumbnails._MEM_CACHE.clear()
    for i in range(1000):
        thumbnails._remember(f"k{i}", object())
    print(f"thumb cache: 1000 inserts -> {len(thumbnails._MEM_CACHE)} entries (bound 128)")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fps_bench_") as tmp:
        root = Path(tmp)
        bench_queue(root)
        bench_watcher(root)
        bench_sanitize(root)
        bench_thumb_cache()


if __name__ == "__main__":
    main()
