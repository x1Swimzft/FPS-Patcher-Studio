"""v1.0.1: previously persisted-but-dead settings now have runtime consumers."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.app.quick_patch import _request as quick_request
from fps_patcher.cli import main as cli_main
from fps_patcher.config import Settings
from fps_patcher.core import patcher as patcher_mod
from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_runner import parse_extra_ffmpeg_args
from fps_patcher.core.models import PatchDoneEvent, PatchRequest
from fps_patcher.core.notify import notify
from fps_patcher.core.patcher import _insert_extra_args, backup_existing_output, patch


def test_extra_ffmpeg_args_are_tokenised_without_a_shell() -> None:
    assert parse_extra_ffmpeg_args("") == []
    assert parse_extra_ffmpeg_args("   ") == []
    assert parse_extra_ffmpeg_args('-movflags +faststart -metadata "title=a b"') == [
        "-movflags",
        "+faststart",
        "-metadata",
        "title=a b",
    ]
    # Shell metacharacters stay inert data because subprocess receives a list.
    assert parse_extra_ffmpeg_args("a; rm -rf /") == ["a;", "rm", "-rf", "/"]
    with pytest.raises(PatchError):
        parse_extra_ffmpeg_args("'unterminated")
    with pytest.raises(PatchError):
        parse_extra_ffmpeg_args("ok\x00bad")


def test_extra_args_are_inserted_before_the_output_path() -> None:
    args = ["-i", "in.mp4", "-c", "copy", "out.mp4"]
    assert _insert_extra_args(args, ["-movflags", "+faststart"]) == [
        "-i",
        "in.mp4",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "out.mp4",
    ]
    assert _insert_extra_args(args, []) == args


def test_backup_never_replaces_an_existing_backup(tmp_path: Path) -> None:
    final = tmp_path / "clip_ts60000.mp4"
    final.write_bytes(b"new output")
    (tmp_path / "clip_ts60000.mp4.bak").write_bytes(b"user file")
    (tmp_path / "clip_ts60000.mp4.1.bak").write_bytes(b"user file 1")

    backup = backup_existing_output(final)

    assert backup.name == "clip_ts60000.mp4.2.bak"
    assert backup.read_bytes() == b"new output"
    assert (tmp_path / "clip_ts60000.mp4.bak").read_bytes() == b"user file"
    assert (tmp_path / "clip_ts60000.mp4.1.bak").read_bytes() == b"user file 1"


def test_backup_original_copies_the_output_being_replaced(
    clip30: Path, ff: Any, tmp_path: Path
) -> None:
    request = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        overwrite=True,
        backup_original=True,
        verify_after=False,
    )
    first = patch(request, ff, lambda _event: None)
    original = first.output.read_bytes()

    patch(request, ff, lambda _event: None)

    backup = Path(str(first.output) + ".bak")
    assert backup.is_file()
    assert backup.read_bytes() == original


def test_verify_after_false_skips_both_verifiers(
    clip30: Path, ff: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("verification must be skipped")

    monkeypatch.setattr(patcher_mod, "verify", boom)
    monkeypatch.setattr(patcher_mod, "verify_payload_integrity", boom)
    request = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        backup_original=False,
        verify_after=False,
    )

    result = patch(request, ff, lambda _event: None)

    assert result.output.is_file()


@pytest.mark.parametrize(("stop_on_error", "expected_calls"), [(True, 1), (False, 2)])
def test_controller_wires_settings_and_stops_on_error(
    tmp_path: Path,
    monkeypatch: Any,
    stop_on_error: bool,
    expected_calls: int,
) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    settings = Settings(
        stop_on_error=stop_on_error,
        verify_after=False,
        backup_original=False,
        extra_ffmpeg_args="-movflags +faststart",
    )
    controller = AppController(settings)
    controller.items.add([first, second])
    controller.items.select_all(True)
    calls: list[PatchRequest] = []

    def fake_patch(
        request: PatchRequest, *_args: Any, **_kwargs: Any
    ) -> Any:
        calls.append(request)
        raise PatchError("boom")

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    controller.start_patch(60000, "direct-atom")
    assert controller._worker is not None
    controller._worker.join(5)

    assert len(calls) == expected_calls
    request = calls[0]
    assert request.verify_after is False
    assert request.backup_original is False
    assert request.extra_ffmpeg_args == "-movflags +faststart"


def test_cli_stop_on_error_halts_after_first_failure(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    calls: list[Path] = []

    def fake_patch(request: PatchRequest, *_args: Any, **_kwargs: Any) -> Any:
        calls.append(request.src)
        raise PatchError("boom")

    monkeypatch.setattr("fps_patcher.cli.patch", fake_patch)
    code = cli_main(
        ["patch", str(first), str(second)],
        Settings(stop_on_error=True),
    )

    assert code == 1
    assert calls == [first]
    assert "boom" in capsys.readouterr().err


def test_notify_dispatches_none_toast_and_sound(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_toast(message: str) -> bool:
        calls.append(message)
        return True

    monkeypatch.setattr("fps_patcher.core.notify.toast", fake_toast)
    beeps: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "winsound",
        SimpleNamespace(MessageBeep=lambda: beeps.append("beep")),
    )

    assert notify("none", "done") is False
    assert notify("toast", "done") is True
    assert calls == ["done"]
    if sys.platform == "win32":
        assert notify("sound", "done") is True
        assert beeps == ["beep"]
    else:
        assert notify("sound", "done") is False


def test_setup_logging_honours_log_to_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from fps_patcher import logging_setup

    logger = logging.getLogger("fps_patcher")
    saved = logger.handlers[:]
    logger.handlers.clear()
    monkeypatch.setattr(logging_setup, "app_data_dir", lambda: tmp_path)
    try:
        logging_setup.setup_logging(False)
        logger.info("file logging off")
        assert list(tmp_path.glob("*.log")) == []

        logging_setup.setup_logging(True)
        logger.info("file logging on")
        for handler in logger.handlers:
            handler.flush()
        assert (tmp_path / "fps_patcher.log").is_file()
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = saved


def test_quick_patch_never_overwrites_when_confirmation_is_on() -> None:
    guarded = quick_request(
        Path("clip.mp4"), Settings(overwrite=True, confirm_overwrite=True)
    )
    assert guarded.overwrite is False
    assert guarded.auto_rename is True

    explicit = quick_request(
        Path("clip.mp4"), Settings(overwrite=True, confirm_overwrite=False)
    )
    assert explicit.overwrite is True


def test_gui_confirm_overwrite_declines_and_accepts(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QMessageBox
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    window.settings.overwrite = True
    window.settings.confirm_overwrite = True
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    window.controller.items.add([video])
    window.controller.items.select_all(True)
    (tmp_path / "clip_ts60000.mp4").write_bytes(b"old output")
    start = MagicMock()
    window.controller.start_patch = start  # type: ignore[method-assign]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    window._start_patch(timescale=60000, strategy="direct-atom")
    assert not start.called

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    window._start_patch(timescale=60000, strategy="direct-atom")
    assert start.called
    window.close()


def test_gui_manual_batch_uses_notify_done(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    window.settings.notify_done = "toast"
    sent: list[str] = []
    window._notify_done = (  # type: ignore[method-assign]
        lambda message: sent.append(message)
    )
    result = MagicMock()
    result.output = tmp_path / "clip_ts60000.mp4"
    result.experimental = False
    event = PatchDoneEvent(
        result=result,
        batch_results=[result],
        failed=[],
        total_files=1,
        cancelled=False,
    )

    window._on_patch_done(event)

    assert sent and "1" in sent[0]
    window.close()
