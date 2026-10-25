"""Entry-point UI selection: no window, event loop or GUI toolkit is started."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

import fps_patcher.__main__ as entry
from fps_patcher.config import Settings
from fps_patcher.ui import main_window as legacy


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, Any]], object]:
    calls: list[tuple[str, Any]] = []
    settings = object()

    class FakeWindow:
        def __init__(self, received: Any) -> None:
            calls.append(("tk", received))

        def mainloop(self) -> None:
            calls.append(("tk.mainloop", None))

    def fake_qt_run(received: Any) -> int:
        calls.append(("qt", received))
        return 0

    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(legacy, "MainWindow", FakeWindow)
    monkeypatch.setattr("fps_patcher.logging_setup.setup_logging", lambda: None)
    monkeypatch.setattr("fps_patcher.ui_qt.app.run", fake_qt_run)
    monkeypatch.delenv("FPS_PATCHER_UI", raising=False)
    return calls, settings


def test_default_is_qt(launches: tuple[list[tuple[str, Any]], object]) -> None:
    calls, settings = launches
    with pytest.raises(SystemExit) as exc:
        entry.main([])
    assert exc.value.code == 0
    assert calls == [("qt", settings)]


def test_ui_flag_selects_tk(launches: tuple[list[tuple[str, Any]], object]) -> None:
    calls, settings = launches
    entry.main(["--ui", "tk"])
    assert calls == [("tk", settings), ("tk.mainloop", None)]


def test_env_selects_tk(
    launches: tuple[list[tuple[str, Any]], object], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, settings = launches
    monkeypatch.setenv("FPS_PATCHER_UI", "tk")
    entry.main([])
    assert calls == [("tk", settings), ("tk.mainloop", None)]


def test_ui_flag_overrides_env(
    launches: tuple[list[tuple[str, Any]], object], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, settings = launches
    monkeypatch.setenv("FPS_PATCHER_UI", "tk")
    with pytest.raises(SystemExit):
        entry.main(["--ui", "qt"])
    assert calls == [("qt", settings)]


def test_ui_flag_stripped_from_sys_argv(
    launches: tuple[list[tuple[str, Any]], object], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, settings = launches
    monkeypatch.setattr(sys, "argv", ["FPSPatcherStudio.exe", "--ui", "tk", "--flag"])
    entry.main()
    assert sys.argv == ["FPSPatcherStudio.exe", "--flag"]
    assert calls == [("tk", settings), ("tk.mainloop", None)]


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
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
