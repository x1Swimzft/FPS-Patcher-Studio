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


def test_repatch_done_video_allowed_and_resets(
    clip30: Path, tmp_path: Path
) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path), overwrite=True))
    assert ctrl.init_ffmpeg() is not None

    ctrl.add_files([clip30])
    _wait_for_probed(ctrl, 1)

    # First patch run
    ctrl.start_patch(60000, "timescale")
    events = _wait_for_patch_done(ctrl)
    done_ev = next(e for e in events if isinstance(e, PatchDoneEvent))
    assert done_ev.total_files == 1
    item = ctrl.items.get(clip30)
    assert item is not None and item.status == "done"

    # clip30 is still selected; re-patching must NOT be blocked
    assert item.selected is True
    ctrl.start_patch(120000, "timescale")
    assert ctrl.busy

    events2 = _wait_for_patch_done(ctrl)
    reset_ev = next(
        (e for e in events2 if isinstance(e, QueueChangedEvent) and e.reason == "reset"),
        None,
    )
    assert reset_ev is not None, "Expected QueueChangedEvent('reset') when re-patching"

    done_ev2 = next(e for e in events2 if isinstance(e, PatchDoneEvent))
    assert done_ev2.total_files == 1
    assert item.status == "done"


def test_clear_queue_resets_current_and_queue(clip30: Path, tmp_path: Path) -> None:
    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    assert ctrl.init_ffmpeg() is not None

    ctrl.add_files([clip30])
    _wait_for_probed(ctrl, 1)
    ctrl.current = ctrl.items.get(clip30).info  # type: ignore[union-attr]
    assert ctrl.current is not None
    assert len(ctrl.queue) == 1
    assert len(ctrl.items) == 1

    ctrl.clear_queue()
    assert len(ctrl.items) == 0
    assert len(ctrl.queue) == 0
    assert ctrl.current is None

    seen: list[object] = []
    ctrl.drain(seen.append)
    assert any(isinstance(e, QueueChangedEvent) and e.reason == "cleared" for e in seen)


def test_clear_queue_blocked_when_busy(tmp_path: Path) -> None:
    import threading

    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    a = _mk(tmp_path, "a.mp4")
    ctrl.add_files([a])
    assert len(ctrl.items) == 1

    stop_event = threading.Event()
    worker = threading.Thread(target=stop_event.wait)
    worker.start()
    ctrl._worker = worker
    try:
        assert ctrl.busy is True
        ctrl.clear_queue()
        assert len(ctrl.items) == 1
        assert len(ctrl.queue) == 1
    finally:
        stop_event.set()
        worker.join()


def test_strings_clear_all() -> None:
    from fps_patcher.ui.strings import t

    assert t("clear_all", "en") == "Clear All"
    assert t("clear_all", "th") == "ล้างทั้งหมด"
    assert t("clear_confirm", "en") == "Clear all files from the queue?"
    assert t("clear_confirm", "th") == "ต้องการล้างรายการไฟล์ทั้งหมดออกจากคิวหรือไม่?"


def test_clear_all_button_ui_and_state(tmp_path: Path) -> None:
    from unittest.mock import PropertyMock, patch

    from fps_patcher.ui.input_list import (
        MAC_ACCENT_BLUE,
        MAC_UNFOCUSED_BORDER,
        MAC_UNFOCUSED_GREY,
        TEXT_SOFT_WHITE,
        TEXT_WHITE,
    )
    from fps_patcher.ui.main_window import MainWindow

    with patch("fps_patcher.ui.main_window.app_data_dir", return_value=tmp_path):
        w = MainWindow(Settings(output_dir=str(tmp_path)))
        w.withdraw()
        try:
            assert len(w.controller.items) == 0
            p1 = tmp_path / "test1.mp4"
            p2 = tmp_path / "test2.mp4"
            p1.write_bytes(b"dummy1")
            p2.write_bytes(b"dummy2")
            w.controller.add_files([p1, p2])
            w.controller.items.set_override(p1, timescale=60000, strategy="direct-atom")
            w._sync_info_panel(p1)
            w.input_list.set_focused_path(p1)
            w.input_list.render()

            assert len(w.controller.items) == 2
            assert w.input_list.lbl_selected_count.cget("text") == "2 of 2 selected"
            assert w.controls._focused_item is not None

            # Retrieve row widgets
            it1 = w.controller.items.get(p1)
            it2 = w.controller.items.get(p2)
            assert it1 is not None and it2 is not None
            row1 = w.input_list._row_widgets[it1.item_id]
            row2 = w.input_list._row_widgets[it2.item_id]
            tokens = w.input_list._theme_mgr.tokens

            # 1. Focused macOS Accent Blue state (Window has OS focus)
            assert row1.is_focused is True
            assert row1.cget("fg_color") == MAC_ACCENT_BLUE
            assert row1.cget("border_color") == MAC_ACCENT_BLUE
            assert row1.lbl_name.cget("text_color") == TEXT_WHITE
            assert row1.lbl_meta.cget("text_color") == TEXT_SOFT_WHITE
            assert row1.btn_remove.cget("text_color") == TEXT_WHITE

            # 2. Unfocused/unselected card remains on normal surface tokens
            assert row2.is_focused is False
            assert row2.cget("fg_color") == tokens.surface
            assert row2.cget("border_color") == tokens.border
            assert row2.lbl_name.cget("text_color") == tokens.text
            assert row2.lbl_meta.cget("text_color") == tokens.muted

            # 3. Window loses OS focus (set_window_focused(False))
            w.set_window_focused(False)
            assert w.input_list.window_focused is False
            assert row1.cget("fg_color") == MAC_UNFOCUSED_GREY
            assert row1.cget("border_color") == MAC_UNFOCUSED_BORDER
            assert row1.lbl_name.cget("text_color") == tokens.text
            assert row1.lbl_meta.cget("text_color") == tokens.text2
            # Unselected row2 still unchanged
            assert row2.cget("fg_color") == tokens.surface

            # 4. Window regains OS focus (set_window_focused(True))
            w.set_window_focused(True)
            assert w.input_list.window_focused is True
            assert row1.cget("fg_color") == MAC_ACCENT_BLUE
            assert row1.cget("border_color") == MAC_ACCENT_BLUE
            assert row1.lbl_name.cget("text_color") == TEXT_WHITE
            assert row1.lbl_meta.cget("text_color") == TEXT_SOFT_WHITE

            # 5. Row remove button state under busy
            w.input_list.set_state(busy=True)
            assert w.input_list.btn_clear_all.cget("state") == "disabled"
            assert row1.btn_remove.cget("state") == "disabled"
            assert row2.btn_remove.cget("state") == "disabled"
            w.input_list.set_state(busy=False)
            assert w.input_list.btn_clear_all.cget("state") == "normal"
            assert row1.btn_remove.cget("state") == "normal"
            assert row2.btn_remove.cget("state") == "normal"

            # 6. Click row remove button for row2
            row2.btn_remove._command()
            assert len(w.controller.items) == 1
            assert w.controller.items.get(p2) is None
            assert w.input_list.lbl_selected_count.cget("text") == "1 of 1 selected"

            # 7. Clear all blocked while controller is busy
            busy_patch = patch.object(
                type(w.controller), "busy", new_callable=PropertyMock, return_value=True
            )
            with busy_patch, patch("tkinter.messagebox.askyesno", return_value=True) as mock_ask:
                w.input_list._clear_all()
                mock_ask.assert_not_called()
            assert len(w.controller.items) == 1

            # 8. Clear all dialog cancelled
            with patch("tkinter.messagebox.askyesno", return_value=False):
                w.input_list._clear_all()
            assert len(w.controller.items) == 1

            # 9. Clear all confirmed: clears queue, resets counter, clears preview and overrides
            with patch("tkinter.messagebox.askyesno", return_value=True):
                w.input_list._clear_all()

            assert len(w.controller.items) == 0
            assert w.input_list.lbl_selected_count.cget("text") == "0 of 0 selected"
            assert w.controls._focused_item is None
            assert w.input_list.preview_name_lbl.cget("text") == "—"
        finally:
            w.destroy()



