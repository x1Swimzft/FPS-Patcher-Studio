"""Windows startup command and registration helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fps_patcher.app import startup


def test_startup_command_frozen_executable_is_quoted(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "executable",
        r"C:\Program Files\FPS Patcher Studio\FPSPatcherStudio.exe",
    )

    command = startup.startup_command()

    assert command == (
        r'"C:\Program Files\FPS Patcher Studio\FPSPatcherStudio.exe" --startup'
    )


def test_startup_command_source_uses_pythonw(monkeypatch: Any, tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    pythonw = scripts / "pythonw.exe"
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(python))

    command = startup.startup_command()

    assert command == f'"{pythonw}" -m fps_patcher --startup'


def test_startup_is_noop_off_windows(monkeypatch: Any) -> None:
    monkeypatch.setattr(startup.os, "name", "posix")

    assert startup.set_startup_enabled(True) is True
    assert startup.set_startup_enabled(False) is True
