from __future__ import annotations

from pathlib import Path

from fps_patcher.app.queue_model import InputQueue


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
