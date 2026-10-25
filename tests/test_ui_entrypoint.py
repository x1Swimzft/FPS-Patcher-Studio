"""Entry-point UI selection: Qt only, legacy Tk values are deprecated."""

from __future__ import annotations

import logging
import subprocess
import sys
import warnings
from typing import Any

import pytest

import fps_patcher.__main__ as entry
from fps_patcher.config import Settings

LEGACY = "fps_patcher.ui.main_window"


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, Any]], object]:
    calls: list[tuple[str, Any]] = []
    settings = object()

    def fake_qt_run(received: Any) -> int:
        calls.append(("qt", received))
        return 0

    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(
        "fps_patcher.logging_setup.setup_logging",
        lambda: logging.getLogger("fps_patcher.entrypoint_test"),
    )
    monkeypatch.setattr("fps_patcher.ui_qt.app.run", fake_qt_run)
    monkeypatch.delenv("FPS_PATCHER_UI", raising=False)
    monkeypatch.delitem(sys.modules, LEGACY, raising=False)
    return calls, settings


def _warning_text(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    caught: list[warnings.WarningMessage],
) -> str:
    out, err = capsys.readouterr()
    parts = [caplog.text, out, err, *(str(item.message) for item in caught)]
    return " ".join(parts).lower()


def _assert_deprecation_notice(text: str) -> None:
    assert any(word in text for word in ("deprecat", "legacy", "warn", "no longer")), text


def test_default_is_qt(launches: tuple[list[tuple[str, Any]], object]) -> None:
    calls, settings = launches
    with pytest.raises(SystemExit) as exc:
        entry.main([])
    assert exc.value.code == 0
    assert calls == [("qt", settings)]
    assert LEGACY not in sys.modules


def test_ui_flag_selects_qt(launches: tuple[list[tuple[str, Any]], object]) -> None:
    calls, settings = launches
    with pytest.raises(SystemExit) as exc:
        entry.main(["--ui", "qt"])
    assert exc.value.code == 0
    assert calls == [("qt", settings)]


def test_ui_flag_tk_warns_and_launches_qt(
    launches: tuple[list[tuple[str, Any]], object],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, settings = launches
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(SystemExit) as exc:
            entry.main(["--ui", "tk"])
    assert exc.value.code == 0
    assert calls == [("qt", settings)]
    assert LEGACY not in sys.modules
    _assert_deprecation_notice(_warning_text(caplog, capsys, caught))


def test_env_tk_warns_and_launches_qt(
    launches: tuple[list[tuple[str, Any]], object],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, settings = launches
    monkeypatch.setenv("FPS_PATCHER_UI", "tk")
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(SystemExit) as exc:
            entry.main([])
    assert exc.value.code == 0
    assert calls == [("qt", settings)]
    assert LEGACY not in sys.modules
    _assert_deprecation_notice(_warning_text(caplog, capsys, caught))


def test_ui_flag_stripped_from_sys_argv(
    launches: tuple[list[tuple[str, Any]], object],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, settings = launches
    monkeypatch.setattr(sys, "argv", ["FPSPatcherStudio.exe", "--ui", "tk", "--flag"])
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(SystemExit):
            entry.main()
    assert sys.argv == ["FPSPatcherStudio.exe", "--flag"]
    assert calls == [("qt", settings)]
    _assert_deprecation_notice(_warning_text(caplog, capsys, caught))


def test_quick_patch_stays_headless() -> None:
    code = (
        "import sys\n"
        "from fps_patcher.__main__ import main\n"
        "try:\n"
        "    main(['--quick-patch'])\n"
        "except SystemExit as exc:\n"
        "    assert exc.code == 2\n"
        "assert 'PySide6' not in sys.modules\n"
        "assert 'tkinter' not in sys.modules\n"
        "assert 'customtkinter' not in sys.modules\n"
        "assert 'fps_patcher.ui.main_window' not in sys.modules\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
