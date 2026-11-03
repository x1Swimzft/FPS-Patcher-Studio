"""History dialog: newest-first listing, empty state and guarded rollback."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox, QTableWidgetItem  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.errors import PatchError  # noqa: E402
from fps_patcher.core.job_history import JobRecord  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import history_dialog as hd  # noqa: E402
from fps_patcher.ui_qt.history_dialog import HistoryDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


class _FakeController:
    def __init__(self, records: list[JobRecord]) -> None:
        self.busy = False
        self.records = records
        self.calls: list[str | None] = []

    def undo_job(self, job_id: str | None = None) -> JobRecord:
        self.calls.append(job_id)
        for index, record in enumerate(self.records):
            if record.job_id == job_id:
                updated = replace(record, rolled_back=True)
                self.records[index] = updated
                return updated
        raise PatchError(f"Job not found: {job_id}")


def _record(
    tmp_path: Path,
    job_id: str,
    timestamp: str,
    *,
    backup: bool = True,
    rolled_back: bool = False,
) -> JobRecord:
    source = tmp_path / f"{job_id}.mp4"
    output = tmp_path / f"{job_id}_ts60000.mp4"
    return JobRecord(
        job_id=job_id,
        timestamp=timestamp,
        src=str(source),
        output=str(output),
        backup=str(source.with_suffix(".mp4.bak")) if backup else None,
        timescale=60000,
        strategy="x1t-mobile",
        platform_profile="tiktok",
        rolled_back=rolled_back,
    )


def _install_history(
    monkeypatch: Any, records: list[JobRecord]
) -> list[int]:
    calls: list[int] = []

    def fake_load(*, history_path: Path | None = None, limit: int = 50) -> list[JobRecord]:
        calls.append(limit)
        return list(records)

    monkeypatch.setattr(hd, "load_history", fake_load)
    return calls


def _dialog(
    qtbot: Any, controller: _FakeController, lang: str = "en"
) -> HistoryDialog:
    settings = Settings(reduce_motion=True, language=lang)
    dialog = HistoryDialog(settings, ThemeManager(settings), controller)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    return dialog


def _cell(dialog: HistoryDialog, row: int, column: int) -> QTableWidgetItem:
    item = dialog.table.item(row, column)
    assert item is not None
    return item


def test_lists_newest_first_with_names_and_status(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    newest = _record(tmp_path, "newest", "2026-11-04T21:15:30+07:00")
    older = _record(
        tmp_path,
        "older",
        "2026-11-03T08:00:00+07:00",
        backup=False,
        rolled_back=True,
    )
    controller = _FakeController([newest, older])
    calls = _install_history(monkeypatch, controller.records)

    dialog = _dialog(qtbot, controller)
    lang = dialog.settings.language

    assert calls == [100]
    assert dialog.table.rowCount() == 2
    assert _cell(dialog, 0, 0).text() == newest.timestamp
    assert _cell(dialog, 0, 1).text() == Path(newest.src).name
    assert _cell(dialog, 0, 2).text() == Path(newest.output).name
    assert _cell(dialog, 0, 1).toolTip() == newest.src
    assert _cell(dialog, 0, 2).toolTip() == newest.output
    assert _cell(dialog, 0, 3).text() == "Yes"
    assert _cell(dialog, 1, 3).text() == "No"
    assert _cell(dialog, 0, 4).text() == t("history_available", lang)
    assert _cell(dialog, 1, 4).text() == t("history_rolled_back", lang)
    assert not dialog.rollback_button.isEnabled()
    assert dialog.table.isHidden() is False
    assert dialog.empty_label.isHidden() is True


def test_rollback_confirms_calls_controller_and_refreshes(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    record = _record(tmp_path, "job1", "2026-11-04T21:15:30+07:00")
    controller = _FakeController([record])
    calls = _install_history(monkeypatch, controller.records)
    questions: list[tuple[Any, ...]] = []
    messages: list[tuple[Any, ...]] = []

    def fake_question(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        questions.append(args)
        return QMessageBox.StandardButton.Yes

    def fake_information(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        messages.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(QMessageBox, "information", fake_information)

    dialog = _dialog(qtbot, controller)
    dialog.table.selectRow(0)
    assert dialog.rollback_button.isEnabled()

    dialog.rollback_button.click()

    assert controller.calls == [record.job_id]
    assert questions[0][2] == t("history_rollback_confirm", dialog.settings.language)
    assert messages[0][2] == t(
        "history_rollback_done", dialog.settings.language
    ).format(path=record.output)
    assert calls == [100, 100]
    assert _cell(dialog, 0, 4).text() == t(
        "history_rolled_back", dialog.settings.language
    )
    assert not dialog.rollback_button.isEnabled()


def test_rollback_error_shows_localized_message(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    class _FailingController(_FakeController):
        def undo_job(self, job_id: str | None = None) -> JobRecord:
            raise PatchError("Backup file is missing")

    record = _record(tmp_path, "broken", "2026-11-04T21:15:30+07:00")
    controller = _FailingController([record])
    _install_history(monkeypatch, controller.records)
    errors: list[tuple[Any, ...]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *args, **kwargs: errors.append(args),
    )

    dialog = _dialog(qtbot, controller)
    dialog.table.selectRow(0)
    dialog.rollback_button.click()

    assert errors[0][2] == t(
        "history_rollback_failed", dialog.settings.language
    ).format(error="Backup file is missing")
    assert _cell(dialog, 0, 4).text() == t(
        "history_available", dialog.settings.language
    )


def test_rolled_back_record_cannot_be_rolled_back_again(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    record = _record(
        tmp_path, "done", "2026-11-04T21:15:30+07:00", rolled_back=True
    )
    controller = _FakeController([record])
    _install_history(monkeypatch, controller.records)

    dialog = _dialog(qtbot, controller)
    dialog.table.selectRow(0)

    assert not dialog.rollback_button.isEnabled()
    dialog.rollback_button.click()
    assert controller.calls == []


def test_busy_controller_disables_rollback(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    record = _record(tmp_path, "busy", "2026-11-04T21:15:30+07:00")
    controller = _FakeController([record])
    controller.busy = True
    _install_history(monkeypatch, controller.records)

    dialog = _dialog(qtbot, controller)
    dialog.table.selectRow(0)

    assert not dialog.rollback_button.isEnabled()
    dialog.rollback_button.click()
    assert controller.calls == []


def test_empty_history_shows_empty_state(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    controller = _FakeController([])
    calls = _install_history(monkeypatch, [])

    dialog = _dialog(qtbot, controller)

    assert calls == [100]
    assert dialog.table.rowCount() == 0
    assert dialog.table.isHidden() is True
    assert dialog.empty_label.isHidden() is False
    assert dialog.empty_label.text() == t(
        "history_empty", dialog.settings.language
    )
    assert not dialog.rollback_button.isEnabled()


def test_unreadable_history_still_opens_empty(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    def broken_load(**kwargs: Any) -> list[JobRecord]:
        raise RuntimeError("corrupt history")

    monkeypatch.setattr(hd, "load_history", broken_load)
    controller = _FakeController([])

    dialog = _dialog(qtbot, controller)

    assert dialog.table.rowCount() == 0
    assert dialog.empty_label.isHidden() is False
