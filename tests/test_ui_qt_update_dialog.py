"""Qt update dialog and update-flow wiring (no network, no real installer)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from fps_patcher import config  # noqa: E402
from fps_patcher.app.controller import AppController  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core import updater  # noqa: E402
from fps_patcher.core.models import UpdateDownloadEvent  # noqa: E402
from fps_patcher.core.updater import UpdateInfo  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import update_dialog as update_dialog_module  # noqa: E402
from fps_patcher.ui_qt.main_window import MainWindow  # noqa: E402
from fps_patcher.ui_qt.update_dialog import UpdateDialog  # noqa: E402


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def append(self, message: str, level: str = "INFO") -> None:
        self.lines.append((message, level))


class FakeButton:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.enabled: bool | None = None
        self.visible: bool | None = None

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def setToolTip(self, _text: str) -> None:
        pass

    def setAccessibleName(self, _text: str) -> None:
        pass

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


def _info(notes: str = "Release notes") -> UpdateInfo:
    return UpdateInfo(
        version="1.3.1",
        tag="v1.3.1",
        notes=notes,
        page_url="https://example.invalid/release",
        asset_name="FPSPatcherStudio-1.3.1.zip",
        asset_url=None,
        asset_size=0,
        sha256=None,
    )


def _dialog(qtbot: Any, notes: str = "Release notes") -> UpdateDialog:
    dialog = UpdateDialog(_info(notes), Settings())
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_dialog_shows_version_notes_and_skip_emits(
    qtbot: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        update_dialog_module, "detect_install_mode", lambda app_dir=None: "installed"
    )
    notes = "line\n" * 400
    settings = Settings()
    dialog = UpdateDialog(_info(notes), settings)
    qtbot.addWidget(dialog)
    dialog.show()

    assert "v1.3.1" in dialog.version_label.text()
    assert t("update_mode_installed", "en") in dialog.mode_label.text()
    assert dialog.notes.toPlainText() == notes
    assert dialog.skip_button.text() == t("update_skip_btn", "en")

    with qtbot.waitSignal(dialog.skip_requested):
        qtbot.mouseClick(dialog.skip_button, Qt.MouseButton.LeftButton)

    assert settings.skipped_update_version == ""


def test_update_click_disables_skip_and_shows_progress(
    qtbot: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        update_dialog_module, "detect_install_mode", lambda app_dir=None: "portable"
    )
    dialog = _dialog(qtbot)
    assert t("update_mode_portable", "en") in dialog.mode_label.text()

    with qtbot.waitSignal(dialog.update_requested):
        qtbot.mouseClick(dialog.update_button, Qt.MouseButton.LeftButton)

    assert dialog.is_downloading()
    assert not dialog.skip_button.isEnabled()
    assert not dialog.update_button.isEnabled()
    assert dialog.progress_bar.isVisible()
    assert dialog.status_label.text() == t("update_downloading", "en", percent=0)

    dialog.download_cancelled()

    assert not dialog.is_downloading()
    assert dialog.skip_button.isEnabled()
    assert dialog.update_button.isEnabled()
    assert not dialog.progress_bar.isVisible()
    assert dialog.status_label.text() == t("update_cancelled", "en")


def test_download_failed_reenables_buttons(qtbot: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        update_dialog_module, "detect_install_mode", lambda app_dir=None: "installed"
    )
    dialog = _dialog(qtbot)

    with qtbot.waitSignal(dialog.update_requested):
        qtbot.mouseClick(dialog.update_button, Qt.MouseButton.LeftButton)

    dialog.download_failed("Download failed: boom")

    assert not dialog.is_downloading()
    assert dialog.skip_button.isEnabled()
    assert dialog.update_button.isEnabled()
    assert dialog.status_label.text() == "Download failed: boom"


def test_controller_cancel_emits_cancelled_event(monkeypatch: Any) -> None:
    started = threading.Event()

    def fake_download(
        info: Any,
        dest: Any,
        progress: Any = None,
        timeout: int = 30,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        assert cancel_event is not None
        started.set()
        assert cancel_event.wait(5)
        raise updater.UpdateCancelledError("cancelled")

    monkeypatch.setattr(updater, "download_update", fake_download)
    controller = AppController(Settings())

    controller.start_update_download(_info())
    assert started.wait(5)
    controller.cancel_update_download()
    worker = controller._update_worker
    assert worker is not None
    worker.join(5)

    events: list[Any] = []
    controller.drain(events.append)
    stages = [
        event.stage for event in events if isinstance(event, UpdateDownloadEvent)
    ]
    assert stages == ["cancelled"]


def test_download_done_defers_while_busy(tmp_path: Path) -> None:
    archive = tmp_path / "update.zip"
    archive.write_bytes(b"zip")
    applied: list[Path] = []
    fake = SimpleNamespace(
        controller=SimpleNamespace(busy=True),
        settings=Settings(),
        console=FakeConsole(),
        update_button=FakeButton(),
        _update_dialog=None,
        _pending_update_path=None,
        _apply_downloaded_update=lambda path: applied.append(path),
    )

    cast(Any, MainWindow._on_update_download)(
        fake, UpdateDownloadEvent("done", path=archive)
    )

    assert applied == []
    assert fake._pending_update_path == archive
    assert fake.update_button.enabled is True
    assert fake.update_button.texts[-1] == t("update_ready_install", "en")
    assert fake.console.lines == [(t("update_busy_deferred", "en"), "INFO")]


def test_skip_handler_persists_version(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    settings = Settings()
    closed: list[bool] = []
    fake = SimpleNamespace(
        settings=settings,
        _update_dialog=SimpleNamespace(close=lambda: closed.append(True)),
    )

    cast(Any, MainWindow._on_update_skip)(
        fake, SimpleNamespace(version="1.3.1")
    )

    assert settings.skipped_update_version == "1.3.1"
    assert closed == [True]


def test_startup_prompt_honors_skipped_version() -> None:
    opened: list[Any] = []
    fake = SimpleNamespace(
        settings=Settings(skipped_update_version="1.3.1"),
        _update_info=SimpleNamespace(version="1.3.1"),
        _update_prompted=False,
        _open_update_dialog=lambda info: opened.append(info),
    )

    cast(Any, MainWindow._prompt_update_on_startup)(fake)

    assert opened == []
    assert fake._update_prompted is True
