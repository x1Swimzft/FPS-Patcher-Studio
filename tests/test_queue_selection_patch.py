from __future__ import annotations

import time
from pathlib import Path

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core.models import LogEvent, PatchDoneEvent, QueueChangedEvent


def _mk(tmp: Path, name: str) -> Path:
    p = tmp / name
    p.write_bytes(b"x")
    return p


def _wait_for_probed(ctrl: AppController, count: int, timeout: float = 5.0) -> list[object]:
    deadline = time.time() + timeout
    seen: list[object] = []
    probed = 0
    while time.time() < deadline:
        ctrl.drain(seen.append)
        for e in seen:
            if isinstance(e, QueueChangedEvent) and e.reason == "probed":
                probed += 1
        if probed >= count:
            return seen
        probed = sum(1 for e in seen if isinstance(e, QueueChangedEvent) and e.reason == "probed")
        time.sleep(0.02)
    return seen


def _wait_for_patch_done(ctrl: AppController, timeout: float = 10.0) -> list[object]:
    deadline = time.time() + timeout
    seen: list[object] = []
    while time.time() < deadline:
        ctrl.drain(seen.append)
        if any(isinstance(e, PatchDoneEvent) for e in seen):
            return seen
        time.sleep(0.02)
    raise AssertionError("timeout waiting for PatchDoneEvent")


def test_add_files_selects_by_default(tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    a = _mk(tmp_path, "a.mp4")
    b = _mk(tmp_path, "b.mp4")

    ctrl.add_files([a, b])
    assert len(ctrl.items) == 2
    it_a = ctrl.items.get(a)
    it_b = ctrl.items.get(b)
    assert it_a is not None and it_a.selected is True
    assert it_b is not None and it_b.selected is True


def test_start_patch_respects_selection_and_skips_unselected(
    clip30: Path, clip5994: Path, tmp_path: Path
) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.add_files([clip30, clip5994])
    _wait_for_probed(ctrl, 2)

    # Deselect clip30, leave clip5994 selected
    ctrl.items.toggle(clip30)
    assert ctrl.items.get(clip30).selected is False  # type: ignore[union-attr]
    assert ctrl.items.get(clip5994).selected is True  # type: ignore[union-attr]

    # start_patch should ONLY patch clip5994
    ctrl.start_patch(60000, "timescale")
    events = _wait_for_patch_done(ctrl)
    done_ev = next(e for e in events if isinstance(e, PatchDoneEvent))

    # Total files patched must be 1, and it must be clip5994
    assert done_ev.total_files == 1
    assert done_ev.result is not None
    assert done_ev.result.src.name == clip5994.name

    # clip30 remains in ready status, NOT done
    item_30 = ctrl.items.get(clip30)
    assert item_30 is not None and item_30.status != "done"

    # clip5994 is marked done
    item_5994 = ctrl.items.get(clip5994)
    assert item_5994 is not None and item_5994.status == "done"


def test_start_patch_with_none_selected_warns_and_does_not_patch(
    clip30: Path, tmp_path: Path
) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.add_files([clip30])
    _wait_for_probed(ctrl, 1)

    # Deselect clip30
    ctrl.items.toggle(clip30)
    assert ctrl.items.get(clip30).selected is False  # type: ignore[union-attr]

    # start_patch should warn and not start any worker
    ctrl.start_patch(60000, "timescale")
    assert not ctrl.busy

    seen: list[object] = []
    ctrl.drain(seen.append)
    log_ev = next(
        (e for e in seen if isinstance(e, LogEvent) and "No selected files to patch" in e.message),
        None,
    )
    assert log_ev is not None
    assert log_ev.level == "WARN"

    item = ctrl.items.get(clip30)
    assert item is not None and item.status != "done"
