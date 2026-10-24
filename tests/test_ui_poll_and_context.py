from __future__ import annotations

from pathlib import Path

import pytest

from fps_patcher.ui.log_console import (
    LogConsole,
    classify_log_level,
    trim_lines_buffer,
)


def test_log_console_set_context_files(tmp_path: Path) -> None:
    # Test that set_context_files exists on LogConsole and works correctly
    target = tmp_path / "target.mp4"
    source = tmp_path / "source.mp4"

    # We can test the method directly on a dummy instance or mock
    class DummyConsole:
        def __init__(self) -> None:
            self.last_target_file: Path | None = None
            self.last_source_file: Path | None = None

    # Verify the method is bound to LogConsole
    assert hasattr(LogConsole, "set_context_files")

    dummy = DummyConsole()
    LogConsole.set_context_files(dummy, target=target, source=source)  # type: ignore[arg-type]
    assert dummy.last_target_file == target
    assert dummy.last_source_file == source


@pytest.mark.parametrize(
    ("level_in", "expected"),
    [
        ("INFO", "INFO"),
        ("OK", "OK"),
        ("WARN", "WARN"),
        ("ERROR", "ERROR"),
        ("CMD", "CMD"),
        ("COMMAND", "CMD"),
        ("DIM", "DIM"),
        ("DEBUG", "DEBUG"),
    ],
)
def test_classify_log_level_explicit_mapping(level_in: str, expected: str) -> None:
    assert classify_log_level("standard message without prefix", level_in) == expected


def test_classify_log_level_inferred_cmd_and_dim() -> None:
    # Infer CMD from command prefixes when level is INFO
    assert classify_log_level("$ ffmpeg -i ...", "INFO") == "CMD"
    assert classify_log_level("ffmpeg -version", "INFO") == "CMD"
    assert classify_log_level("$ ffmpeg -i ...") == "CMD"
    assert classify_log_level("ffmpeg -version") == "CMD"

    # Infer DIM from dim/verbose prefixes when level is INFO
    assert classify_log_level("frame= 120 fps=60", "INFO") == "DIM"
    assert classify_log_level("[DIM] details", "INFO") == "DIM"
    assert classify_log_level("frame= 120 fps=60") == "DIM"
    assert classify_log_level("[DIM] details") == "DIM"


def test_trim_lines_buffer_caps_over_limit() -> None:
    lines = [f"line {i}" for i in range(5000)]
    kept, dropped_count = trim_lines_buffer(lines, 200)

    assert len(kept) == 200
    assert dropped_count == 4800
    assert kept == lines[4800:]
    assert kept[0] == "line 4800"
    assert kept[-1] == "line 4999"


def test_trim_lines_buffer_leaves_within_limit_untouched() -> None:
    # Short list (< max_lines)
    short = [f"line {i}" for i in range(50)]
    kept_short, dropped_short = trim_lines_buffer(short, 200)
    assert kept_short == short
    assert dropped_short == 0

    # Exact max_lines (== max_lines)
    exact = [f"line {i}" for i in range(200)]
    kept_exact, dropped_exact = trim_lines_buffer(exact, 200)
    assert kept_exact == exact
    assert dropped_exact == 0

    # Empty list
    empty: list[str] = []
    kept_empty, dropped_empty = trim_lines_buffer(empty, 200)
    assert kept_empty == []
    assert dropped_empty == 0


def test_main_window_configure_debouncing() -> None:
    from typing import Any
    from unittest.mock import MagicMock

    from fps_patcher.ui.main_window import MainWindow

    class DummyWindow:
        _last_window_dims: tuple[int, int] | None = None
        _configure_debounce_timer: Any = None

        def __init__(self) -> None:
            self.after = MagicMock(side_effect=["timer_1", "timer_2", "timer_3"])
            self.after_cancel = MagicMock()
            self._on_window_resized = MagicMock()

    class DummyEvent:
        def __init__(self, widget: Any, width: int, height: int) -> None:
            self.widget = widget
            self.width = width
            self.height = height

    win = DummyWindow()

    # Event from child widget -> ignored
    child_event = DummyEvent(widget="child_widget", width=1000, height=800)
    MainWindow._on_window_configure(win, child_event)  # type: ignore[arg-type]
    assert win._last_window_dims is None
    win.after.assert_not_called()
    win.after_cancel.assert_not_called()

    # Window dimensions <= 1 -> ignored
    zero_event = DummyEvent(widget=win, width=1, height=1)
    MainWindow._on_window_configure(win, zero_event)  # type: ignore[arg-type]
    assert win._last_window_dims is None
    win.after.assert_not_called()

    # First event from root window -> recorded and timer scheduled (80ms)
    root_event1 = DummyEvent(widget=win, width=1120, height=760)
    MainWindow._on_window_configure(win, root_event1)  # type: ignore[arg-type]
    assert win._last_window_dims == (1120, 760)
    win.after.assert_called_once_with(80, win._on_window_resized)
    win.after_cancel.assert_not_called()
    assert win._configure_debounce_timer == "timer_1"

    # Duplicate event with same dimensions -> debounced / ignored (timer not touched)
    root_event2 = DummyEvent(widget=win, width=1120, height=760)
    MainWindow._on_window_configure(win, root_event2)  # type: ignore[arg-type]
    assert win._last_window_dims == (1120, 760)
    assert win.after.call_count == 1
    win.after_cancel.assert_not_called()

    # Resize event with new dimensions -> cancels existing timer and schedules new 80ms timer
    root_event3 = DummyEvent(widget=win, width=1280, height=800)
    MainWindow._on_window_configure(win, root_event3)  # type: ignore[arg-type]
    assert win._last_window_dims == (1280, 800)
    win.after_cancel.assert_called_once_with("timer_1")
    assert win.after.call_count == 2
    win.after.assert_called_with(80, win._on_window_resized)
    assert win._configure_debounce_timer == "timer_2"


def test_main_window_map_unmap_minimized_lifecycle() -> None:
    from unittest.mock import MagicMock

    from fps_patcher.ui.main_window import MainWindow

    class DummyWindow:
        def __init__(self) -> None:
            self._is_minimized = False
            self.flushed = False
            self.after = MagicMock()
            self._force_win32_repaint = MagicMock()

        def _flush_coalesced_ui_sync(self) -> None:
            self.flushed = True

    win = DummyWindow()
    unmap_ev = MagicMock(widget=win)
    map_ev = MagicMock(widget=win)

    # Unmap -> minimized
    MainWindow._on_window_unmap(win, unmap_ev)  # type: ignore[arg-type]
    assert win._is_minimized is True
    assert win.flushed is False

    # Map -> restored and flushes coalesced sync
    MainWindow._on_window_map(win, map_ev)  # type: ignore[arg-type]
    assert win._is_minimized is False
    assert win.flushed is True
    assert win.after.call_count == 2
    win.after.assert_any_call(16, win._force_win32_repaint)
    win.after.assert_any_call(80, win._force_win32_repaint)


def test_main_window_handle_batch_minimized_coalescing() -> None:
    from unittest.mock import MagicMock

    from fps_patcher.core.models import LogEvent, ProgressEvent, QueueChangedEvent
    from fps_patcher.ui.main_window import MainWindow

    class DummyWindow:
        def __init__(self) -> None:
            self._is_minimized = True
            self._pending_minimized_logs: list[tuple[str, str]] = []
            self._pending_minimized_progress: ProgressEvent | None = None
            self._pending_minimized_queue_dirty = False
            self._pending_minimized_info_panel_dirty = False
            self.controller = MagicMock()
            self.console = MagicMock()
            self.controls = MagicMock()
            self.input_list = MagicMock()
            self.settings = MagicMock(open_when_done=False)

        @property
        def is_minimized(self) -> bool:
            return self._is_minimized

    win = DummyWindow()
    events = [
        LogEvent("test log 1", "INFO"),
        LogEvent("test log 2", "OK"),
        ProgressEvent(file_fraction=0.5, fraction=0.25, file_index=1, total_files=4),
        QueueChangedEvent("added"),
    ]

    MainWindow._handle_batch(win, events)  # type: ignore[arg-type]

    # Console, controls, input_list visual renders should NOT be called while minimized
    win.console.append_batch.assert_not_called()
    win.controls.set_batch_progress.assert_not_called()
    win.input_list.render.assert_not_called()

    # Events should be safely coalesced in pending buffers
    assert len(win._pending_minimized_logs) == 2
    assert win._pending_minimized_logs[0] == ("test log 1", "INFO")
    assert win._pending_minimized_progress is not None
    assert win._pending_minimized_progress.fraction == 0.25
    assert win._pending_minimized_queue_dirty is True
    assert win._pending_minimized_info_panel_dirty is True


def test_main_window_update_available_event_and_show_button() -> None:
    from typing import Any
    from unittest.mock import MagicMock

    from fps_patcher.core.models import UpdateAvailableEvent
    from fps_patcher.ui.main_window import MainWindow
    from fps_patcher.ui.strings import t

    class DummyWindow:
        def __init__(self) -> None:
            self.is_minimized = False
            self._update_info: Any = None
            self.settings = MagicMock(language="en", open_when_done=False)
            self.btn_update = MagicMock()
            self.btn_update.winfo_ismapped.return_value = False

        def _show_update_button(self, info: Any) -> None:
            MainWindow._show_update_button(self, info)  # type: ignore[arg-type]

    win = DummyWindow()
    fake_info = MagicMock(version="0.6.0")

    # In _handle_batch: UpdateAvailableEvent updates _update_info and calls _show_update_button
    event = UpdateAvailableEvent(info=fake_info)
    MainWindow._handle_batch(win, [event])  # type: ignore[arg-type]

    assert win._update_info == fake_info
    expected_text = t("update_available_btn", "en", version="0.6.0")
    win.btn_update.configure.assert_called_once_with(text=expected_text, state="normal")
    win.btn_update.pack.assert_called_once_with(side="left", padx=(8, 0))

    # Calling _show_update_button when already mapped should not pack again
    win.btn_update.reset_mock()
    win.btn_update.winfo_ismapped.return_value = True
    MainWindow._show_update_button(win, fake_info)  # type: ignore[arg-type]
    win.btn_update.configure.assert_called_once_with(text=expected_text, state="normal")
    win.btn_update.pack.assert_not_called()


def test_main_window_on_update_clicked(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import Any
    from unittest.mock import MagicMock

    from fps_patcher.ui.main_window import MainWindow
    from fps_patcher.ui.strings import t

    class DummyWindow:
        def __init__(self) -> None:
            self._update_info: Any = None
            self.settings = MagicMock(language="en")
            self.btn_update = MagicMock()
            self.controller = MagicMock()

    win = DummyWindow()

    # Case 1: _update_info is None -> does nothing
    MainWindow._on_update_clicked(win)  # type: ignore[arg-type]
    win.btn_update.configure.assert_not_called()
    win.controller.start_update_download.assert_not_called()

    # Set update info
    fake_info = MagicMock(version="0.6.0", notes="Bug fixes and improvements")
    win._update_info = fake_info

    # Case 2: askyesno returns False -> does nothing
    askyesno_mock = MagicMock(return_value=False)
    monkeypatch.setattr("fps_patcher.ui.main_window.messagebox.askyesno", askyesno_mock)

    MainWindow._on_update_clicked(win)  # type: ignore[arg-type]
    askyesno_mock.assert_called_once()
    win.btn_update.configure.assert_not_called()
    win.controller.start_update_download.assert_not_called()

    # Case 3: askyesno returns True -> disables btn_update and starts download
    askyesno_mock.reset_mock()
    askyesno_mock.return_value = True

    MainWindow._on_update_clicked(win)  # type: ignore[arg-type]
    askyesno_mock.assert_called_once()
    expected_text = t("update_downloading", "en", percent=0)
    win.btn_update.configure.assert_called_once_with(text=expected_text, state="disabled")
    win.controller.start_update_download.assert_called_once_with(fake_info)


def test_main_window_handle_update_download_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import Any
    from unittest.mock import MagicMock

    from fps_patcher.core.models import UpdateDownloadEvent
    from fps_patcher.ui.main_window import MainWindow
    from fps_patcher.ui.strings import t

    class DummyWindow:
        def __init__(self) -> None:
            self._update_info: Any = MagicMock(version="0.6.0")
            self.settings = MagicMock(language="en")
            self.btn_update = MagicMock()
            self._on_close = MagicMock()
            self._show_update_button = MagicMock()

    win = DummyWindow()

    # 1. stage == "downloading" -> updates btn_update text with percent and disabled state
    dl_event = UpdateDownloadEvent(stage="downloading", downloaded=75, total=100)
    MainWindow._handle_update_download_event(win, dl_event)  # type: ignore[arg-type]
    expected_dl_text = t("update_downloading", "en", percent=75)
    win.btn_update.configure.assert_called_once_with(text=expected_dl_text, state="disabled")

    # 2. stage == "done" with successful installer launch -> launches installer and closes window
    installer_path = Path("E:/test/FPSPatcher-Setup.exe")
    done_event = UpdateDownloadEvent(stage="done", path=installer_path)

    launch_mock = MagicMock()
    monkeypatch.setattr("fps_patcher.core.updater.launch_installer", launch_mock)

    win.btn_update.reset_mock()
    MainWindow._handle_update_download_event(win, done_event)  # type: ignore[arg-type]
    win.btn_update.configure.assert_called_once_with(
        text=t("update_ready_launch", "en"), state="disabled"
    )
    launch_mock.assert_called_once_with(installer_path)
    win._on_close.assert_called_once()

    # 3. stage == "done" with failing installer launch -> shows error and re-enables button
    launch_mock.side_effect = RuntimeError("Cannot execute binary")
    showerror_mock = MagicMock()
    monkeypatch.setattr("fps_patcher.ui.main_window.messagebox.showerror", showerror_mock)

    win._on_close.reset_mock()
    win._show_update_button.reset_mock()
    MainWindow._handle_update_download_event(win, done_event)  # type: ignore[arg-type]
    showerror_mock.assert_called_once_with(
        t("app_title", "en"),
        t("update_failed", "en", error="Cannot execute binary"),
    )
    win._show_update_button.assert_called_once_with(win._update_info)
    win._on_close.assert_not_called()

    # 4. stage == "error" (generic) -> calls showerror and re-enables update button
    showerror_mock.reset_mock()
    win._show_update_button.reset_mock()
    err_event = UpdateDownloadEvent(stage="error", error="Network connection lost")
    MainWindow._handle_update_download_event(win, err_event)  # type: ignore[arg-type]
    showerror_mock.assert_called_once_with(
        t("app_title", "en"),
        t("update_failed", "en", error="Network connection lost"),
    )
    win._show_update_button.assert_called_once_with(win._update_info)

    # 5. stage == "error" (SHA-256) -> calls showerror with SHA-256 specific message
    showerror_mock.reset_mock()
    win._show_update_button.reset_mock()
    sha_err_event = UpdateDownloadEvent(stage="error", error="SHA-256 verification failed")
    MainWindow._handle_update_download_event(win, sha_err_event)  # type: ignore[arg-type]
    showerror_mock.assert_called_once_with(
        t("app_title", "en"),
        t("update_sha256_failed", "en"),
    )
    win._show_update_button.assert_called_once_with(win._update_info)


def test_card_click_coalesces_repaint_and_focuses_last_card() -> None:
    from unittest.mock import MagicMock

    from fps_patcher.app.queue_model import QueueItem
    from fps_patcher.ui.input_list import InputList

    a = QueueItem(path=Path("a.mp4"))
    b = QueueItem(path=Path("b.mp4"))

    class DummyList:
        def __init__(self) -> None:
            self.controller = MagicMock()
            self.controller.items.get = lambda p: a if p == a.path else b
            self.controller.items.items = [a, b]
            self.controller.items.selected.return_value = []
            self.controller.current_patching_path = None
            self.controller.current = None
            self._focused_path = None
            self._focus_paint_timer = None
            self._painted_focus_id = None
            self._on_focus_change = MagicMock()
            self.after = MagicMock(side_effect=["t1", "t2"])
            self.after_cancel = MagicMock()
            self._update_row_focus = MagicMock()
            self._update_preview_strip = MagicMock()
            self._paint_focus = MagicMock()
            self._resolve_active_item = lambda items: next(
                (i for i in items if i.path == self._focused_path), None
            )

    lst = DummyList()

    InputList._on_card_clicked(lst, a.path)  # type: ignore[arg-type]
    lst._update_row_focus.assert_not_called()
    lst.after.assert_called_once_with(16, lst._paint_focus)

    # Second click cancels the pending paint instead of repainting both cards
    InputList._on_card_clicked(lst, b.path)  # type: ignore[arg-type]
    lst.after_cancel.assert_called_once_with("t1")
    lst._update_row_focus.assert_not_called()

    InputList._paint_focus(lst)  # type: ignore[arg-type]
    assert lst._painted_focus_id == b.item_id
    focused = [
        c.args[0].item_id for c in lst._update_row_focus.call_args_list if c.kwargs["is_focused"]
    ]
    assert focused == [b.item_id]
    lst._update_preview_strip.assert_called_once_with(b)

    # Same selection again -> no repaint at all
    lst._update_row_focus.reset_mock()
    InputList._paint_focus(lst)
    lst._update_row_focus.assert_not_called()


def test_queue_item_caches_resolved_path() -> None:
    from fps_patcher.app.queue_model import QueueItem

    item = QueueItem(path=Path("a.mp4"))
    assert item.resolved == Path("a.mp4").resolve()
    assert item.item_id

