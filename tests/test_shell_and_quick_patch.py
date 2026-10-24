"""Phase 2 (v0.7.0): HKCU Explorer verb and headless quick patch (no Tk)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.app import quick_patch, shell_integration
from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchError


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_WRITE = 1
    KEY_READ = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.keys: dict[str, dict[str, str]] = {}

    def CreateKeyEx(self, root: Any, path: str, reserved: int, access: int) -> str:
        self.keys.setdefault(path, {})
        return path

    def CloseKey(self, key: str) -> None:
        return None

    def SetValueEx(
        self, key: str, name: str, reserved: int, typ: int, value: str
    ) -> None:
        self.keys[key][name] = value

    def OpenKey(self, root: Any, path: str, reserved: int, access: int) -> str:
        if path not in self.keys:
            raise FileNotFoundError(path)
        return path

    def QueryValueEx(self, key: str, name: str) -> tuple[str, int]:
        return self.keys[key][name], self.REG_SZ

    def DeleteKey(self, root: Any, path: str) -> None:
        if path not in self.keys:
            raise FileNotFoundError(path)
        del self.keys[path]


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> FakeWinreg:
    fake = FakeWinreg()
    monkeypatch.setattr(shell_integration, "winreg", fake)
    return fake


def test_registry_install_query_uninstall(fake_registry: FakeWinreg) -> None:
    assert not shell_integration.is_installed()

    shell_integration.install(Path(r"C:\Apps\FPS Patcher Studio.exe"))
    assert shell_integration.is_installed()

    for ext in (".mp4", ".mov"):
        command = fake_registry.keys[
            rf"Software\Classes\SystemFileAssociations\{ext}"
            r"\shell\FPSPatcherStudio\command"
        ][""]
        assert "--quick-patch" in command
        assert '"%1"' in command
        label = fake_registry.keys[
            rf"Software\Classes\SystemFileAssociations\{ext}\shell\FPSPatcherStudio"
        ][""]
        assert label == shell_integration.LABEL

    shell_integration.uninstall()
    assert not shell_integration.is_installed()


def test_registry_install_is_idempotent(fake_registry: FakeWinreg) -> None:
    shell_integration.install()
    shell_integration.install()
    assert shell_integration.is_installed()


def test_command_quoting_handles_spaces() -> None:
    command = shell_integration.quick_patch_command(Path(r"C:\Program Files\app.exe"))
    assert command.startswith('"C:\\Program Files\\app.exe"')
    assert command.endswith('--quick-patch "%1"')


def test_quick_patch_target_parsing() -> None:
    from fps_patcher.__main__ import _quick_patch_target

    assert _quick_patch_target(["--quick-patch", "C:\\clip.mp4"]) == "C:\\clip.mp4"
    assert _quick_patch_target(["--quick-patch"]) == ""
    assert _quick_patch_target(["--quick-patch", "--other"]) == ""
    assert _quick_patch_target(["clip.mp4"]) is None


def test_quick_patch_success_runs_headless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    out = tmp_path / "clip_60000fps.mp4"
    settings = Settings()
    calls: dict[str, Any] = {}
    toasts: list[str] = []

    def fake_patch(request: Any, ffmpeg: Any, emit: Any) -> SimpleNamespace:
        calls["request"] = request
        return SimpleNamespace(output=out)

    monkeypatch.setattr(quick_patch, "patch", fake_patch)
    monkeypatch.setattr(quick_patch, "_ffmpeg", lambda _settings: None)
    monkeypatch.setattr(quick_patch, "toast", toasts.append)
    settings.fix_color_tag = True
    settings.scrub_metadata = True

    assert quick_patch.run(clip, settings) == 0
    request = calls["request"]
    assert request.src == clip
    assert request.out_dir == tmp_path
    assert request.timescale == quick_patch.QUICK_PATCH_TIMESCALE
    assert request.strategy == settings.strategy
    assert request.fix_color_tag is True
    assert request.scrub_metadata is True
    assert toasts and "complete" in toasts[0]


def test_quick_patch_failure_returns_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    toasts: list[str] = []
    monkeypatch.setattr(
        quick_patch, "patch", lambda *a, **k: (_ for _ in ()).throw(PatchError("bad"))
    )
    monkeypatch.setattr(quick_patch, "_ffmpeg", lambda _settings: None)
    monkeypatch.setattr(quick_patch, "toast", toasts.append)

    assert quick_patch.run(clip, Settings()) == 1
    assert toasts and "failed" in toasts[0]


def test_quick_patch_imports_no_tk() -> None:
    code = (
        "import sys;"
        "import fps_patcher.app.quick_patch;"
        "import fps_patcher.app.watcher;"
        "import fps_patcher.app.shell_integration;"
        "assert 'tkinter' not in sys.modules;"
        "assert 'customtkinter' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
