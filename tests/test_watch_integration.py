"""Phase 2 (v0.7.0): Qt MainWindow watch-inbox drain without a display.

The drain method is called unbound on a stub so no window or event loop is built;
this keeps the test fast and headless while still exercising the real code path.
"""

from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fps_patcher.app.quick_patch import QUICK_PATCH_TIMESCALE
from fps_patcher.config import Settings
from fps_patcher.ui_qt.main_window import MainWindow


class FakeController:
    def __init__(self, *, busy: bool = False, consumes: bool = True) -> None:
        self.busy = busy
        self.consumes = consumes
        self.added: list[tuple[list[Path], bool]] = []
        self.started: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def add_files(self, paths: list[Path], select: bool = True) -> None:
        self.added.append((paths, select))

    def start_patch(self, *args: Any, **kwargs: Any) -> None:
        self.started.append((args, kwargs))
        if self.consumes:
            self.busy = True


class FakeQueueView:
    def __init__(self) -> None:
        self.refreshes = 0

    def refresh(self) -> None:
        self.refreshes += 1


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def append(self, message: str, level: str = "INFO") -> None:
        self.lines.append((message, level))


def _stub(controller: FakeController, paths: list[Path]) -> Any:
    inbox: queue.Queue[Path] = queue.Queue()
    for path in paths:
        inbox.put(path)
    return SimpleNamespace(
        settings=Settings(),
        controller=controller,
        _watch_inbox=inbox,
        _watch_batch_active=False,
        queue_view=FakeQueueView(),
        console=FakeConsole(),
    )


def test_drain_queues_only_watched_paths(tmp_path: Path) -> None:
    watched = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    fake = _stub(FakeController(), watched)

    MainWindow._drain_watch_inbox(fake)

    controller = fake.controller
    assert controller.added == [(watched, False)]
    assert fake.queue_view.refreshes == 1
    (args, kwargs) = controller.started[0]
    assert args == (QUICK_PATCH_TIMESCALE, fake.settings.strategy)
    assert kwargs == {"only_selected": False, "only_paths": watched}
    assert fake._watch_batch_active is True
    assert fake._watch_inbox.empty()


def test_drain_is_skipped_while_busy(tmp_path: Path) -> None:
    watched = [tmp_path / "a.mp4"]
    fake = _stub(FakeController(busy=True), watched)

    MainWindow._drain_watch_inbox(fake)

    assert fake.controller.added == []
    assert fake._watch_inbox.qsize() == 1
    assert fake._watch_batch_active is False


def test_drain_clears_batch_flag_when_start_is_refused(tmp_path: Path) -> None:
    fake = _stub(FakeController(consumes=False), [tmp_path / "a.mp4"])

    MainWindow._drain_watch_inbox(fake)

    assert fake.controller.started
    assert fake._watch_batch_active is False


def test_drain_does_nothing_for_empty_inbox(tmp_path: Path) -> None:
    fake = _stub(FakeController(), [])

    MainWindow._drain_watch_inbox(fake)

    assert fake.controller.added == []
    assert fake.controller.started == []


def test_controller_start_patch_accepts_only_paths() -> None:
    # Signature guard: the UI passes only_paths as a keyword.
    import inspect

    from fps_patcher.app.controller import AppController

    assert "only_paths" in inspect.signature(AppController.start_patch).parameters
