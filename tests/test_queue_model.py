from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from fps_patcher.app.queue_model import InputQueue
from fps_patcher.core.models import VideoInfo


def _mk(tmp: Path, name: str) -> Path:
    p = tmp / name
    p.write_bytes(b"x")
    return p


def test_add_appends_and_dedupes(tmp_path: Path) -> None:
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mov")
    assert q.add([a]).added == [a]
    r = q.add([a, b])
    assert r.duplicates == [a] and r.added == [b]
    assert len(q) == 2  # second add did not replace first


def test_rejects_bad_files(tmp_path: Path) -> None:
    q = InputQueue()
    txt = _mk(tmp_path, "n.txt")
    r = q.add([txt, tmp_path / "missing.mp4"])
    assert len(r.rejected) == 2 and len(q) == 0


def test_select_remove_clear(tmp_path: Path) -> None:
    q = InputQueue()
    ps = [_mk(tmp_path, f"{i}.mp4") for i in range(3)]
    q.add(ps)
    q.toggle(ps[0])
    q.toggle(ps[2])
    assert q.remove_selected() == 2
    assert q.paths() == [ps[1]]
    q.select_all()
    assert len(q.selected()) == 1
    q.clear()
    assert len(q) == 0


def test_move_and_override(tmp_path: Path) -> None:
    q = InputQueue()
    ps = [_mk(tmp_path, f"{i}.mp4") for i in range(3)]
    q.add(ps)
    q.move(ps[2], 0)
    assert q.paths()[0] == ps[2]
    q.set_override(ps[0], timescale=120000, strategy="v4-forensic")
    it = q.get(ps[0])
    assert it and it.timescale == 120000 and it.strategy == "v4-forensic"


def test_status_and_run_snapshot(tmp_path: Path) -> None:
    q = InputQueue()
    ps = [_mk(tmp_path, f"{i}.mp4") for i in range(3)]
    q.add(ps)
    q.set_status(ps[0], "done")
    q.set_status(ps[1], "failed", error="boom")
    assert [i.path for i in q.snapshot_for_run(False)] == ps[1:]
    assert q.reset_failed() == 1
    q.toggle(ps[2])
    assert [i.path for i in q.snapshot_for_run(True)] == [ps[2]]


def test_item_id_stable(tmp_path: Path) -> None:
    q = InputQueue()
    a = _mk(tmp_path, "a.mp4")
    q.add([a])
    it = q.get(a)
    assert it and len(it.item_id) == 10 and it.item_id[3] == "_"


def test_add_resolves_each_path_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fps_patcher.app.queue_model import short_id

    calls: list[Path] = []
    original = Path.resolve

    def counting(self: Path, strict: bool = False) -> Path:
        calls.append(self)
        return original(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", counting)
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")

    assert q.add([a, b]).added == [a, b]
    assert len(calls) == 2  # one per newly added path, no duplicate work
    calls.clear()

    assert q.add([a]).duplicates == [a]
    assert len(calls) == 1  # duplicate check resolves the new path only

    item = q.get(a)
    assert item is not None
    assert item.resolved == a.resolve()
    assert item.item_id == short_id(a)


def test_queue_lock_skipping(tmp_path: Path) -> None:
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")
    q.add([a, b])
    q.select_all()
    # Removing selected while 'a' is locked skips 'a'
    removed = q.remove_selected(locked_path=a)
    assert removed == 1
    assert q.paths() == [a]

    # Clearing while 'a' is locked preserves 'a'
    q.add([b])
    q.clear(locked_path=a)
    assert q.paths() == [a]


def test_queue_persistence_roundtrip_and_pruning(tmp_path: Path) -> None:
    save_file = tmp_path / "queue.json"
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")
    q.add([a, b])
    q.toggle(a)
    q.set_override(a, timescale=60000, strategy="direct-atom")

    # Save to disk
    q.save(save_file)
    assert save_file.exists()

    # Delete b to verify auto-prune on reload
    b.unlink()

    loaded = InputQueue.load(save_file)
    assert len(loaded) == 1
    item_a = loaded.get(a)
    assert item_a is not None
    assert item_a.selected is True
    assert item_a.timescale == 60000
    assert item_a.strategy == "direct-atom"


def test_reset_for_run(tmp_path: Path) -> None:
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")
    q.add([a, b])
    info_a = VideoInfo(
        path=a,
        codec="h264",
        width=1920,
        height=1080,
        avg_fps=Fraction(30, 1),
        r_fps=Fraction(30, 1),
        duration_s=10.0,
        timescale=30000,
        nb_frames=300,
        has_audio=True,
        stream_count=2,
    )
    q.set_info(a, info_a)
    q.set_status(a, "done", output=tmp_path / "out_a.mp4")
    item_a = q.get(a)
    assert item_a is not None
    item_a.progress = 1.0

    q.set_status(b, "failed", error="Failed to patch")
    item_b = q.get(b)
    assert item_b is not None
    item_b.progress = 0.5

    # Reset both for run
    q.reset_for_run([a, b])

    assert item_a.status == "ready"
    assert item_a.error is None
    assert item_a.progress == 0.0
    assert item_a.output is None

    assert item_b.status == "pending"  # info is None
    assert item_b.error is None
    assert item_b.progress == 0.0
    assert item_b.output is None


def test_set_info_does_not_downgrade_terminal_status(tmp_path: Path) -> None:
    q = InputQueue()
    a = _mk(tmp_path, "late.mp4")
    q.add([a])
    q.set_status(a, "done", output=tmp_path / "out.mp4")

    q.set_info(
        a,
        VideoInfo(
            path=a,
            codec="h264",
            width=1,
            height=1,
            avg_fps=Fraction(30),
            r_fps=Fraction(30),
            duration_s=1.0,
            timescale=30000,
            nb_frames=30,
            has_audio=False,
            stream_count=1,
        ),
    )

    item = q.get(a)
    assert item is not None
    assert item.status == "done"  # a late probe result must not resurrect the row
    assert item.info is not None


def test_snapshot_for_run_allows_done_and_error_when_selected(tmp_path: Path) -> None:
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")
    q.add([a, b])
    q.set_status(a, "done")
    q.set_status(b, "failed", error="fail")

    # Select both
    q.select_all(True)
    snap = q.snapshot_for_run(only_selected=True)
    assert [i.path for i in snap] == [a, b]

    # Select only done item a
    q.select_all(False)
    q.toggle(a)
    snap_a = q.snapshot_for_run(only_selected=True)
    assert [i.path for i in snap_a] == [a]


def test_snapshot_for_run_when_all_done_allows_repatch(tmp_path: Path) -> None:
    q = InputQueue()
    a, b = _mk(tmp_path, "a.mp4"), _mk(tmp_path, "b.mp4")
    q.add([a, b])
    q.set_status(a, "done")
    q.set_status(b, "done")

    # When all are done and only_selected=False, it should allow re-patching all
    snap = q.snapshot_for_run(only_selected=False)
    assert [i.path for i in snap] == [a, b]
