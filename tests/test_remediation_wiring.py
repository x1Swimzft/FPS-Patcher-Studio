"""v2.0.0 Slice 4: Pillar A auto-fix flags reach Settings, controller, quick patch and CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.app import quick_patch
from fps_patcher.app.controller import AppController
from fps_patcher.cli import main as cli_main
from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import PatchRequest

_LOSSY_WARNING = (
    "[WARN] Lossy video re-encode enabled (VFR/codec/resolution auto-fix). "
    "The video stream will be re-encoded to H.264."
)


def test_settings_remediation_defaults_and_legacy_load(tmp_path: Path) -> None:
    defaults = Settings()
    assert defaults.auto_fix_vfr is False
    assert defaults.auto_fix_codec is False
    assert defaults.auto_cap_resolution is False

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"ffmpeg_dir": "C:/ffmpeg"}), encoding="utf-8")
    loaded = Settings.load(legacy)
    assert loaded.auto_fix_vfr is False
    assert loaded.auto_fix_codec is False
    assert loaded.auto_cap_resolution is False


def test_settings_remediation_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(auto_fix_vfr=True, auto_fix_codec=True, auto_cap_resolution=True).save(path)

    loaded = Settings.load(path)
    assert loaded.auto_fix_vfr is True
    assert loaded.auto_fix_codec is True
    assert loaded.auto_cap_resolution is True


def test_controller_request_carries_remediation_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    settings = Settings(
        auto_fix_vfr=True,
        auto_fix_codec=True,
        auto_cap_resolution=True,
        verify_after=False,
        backup_original=False,
    )
    controller = AppController(settings)
    controller.items.add([src])
    controller.items.select_all(True)
    captured: list[PatchRequest] = []

    def fake_patch(
        request: PatchRequest, *_args: Any, **_kwargs: Any
    ) -> Any:
        captured.append(request)
        raise PatchError("boom")

    monkeypatch.setattr("fps_patcher.app.controller.patch", fake_patch)
    controller.start_patch(60000, "direct-atom")
    assert controller._worker is not None
    controller._worker.join(5)

    assert len(captured) == 1
    assert captured[0].auto_fix_vfr is True
    assert captured[0].auto_fix_codec is True
    assert captured[0].auto_cap_resolution is True


def test_quick_patch_request_carries_remediation_settings() -> None:
    settings = Settings(
        auto_fix_vfr=True,
        auto_fix_codec=True,
        auto_cap_resolution=True,
    )

    request = quick_patch._request(Path("clip.mp4"), settings)

    assert request.auto_fix_vfr is True
    assert request.auto_fix_codec is True
    assert request.auto_cap_resolution is True


def _bind_cli_fakes(
    monkeypatch: pytest.MonkeyPatch,
    ff: FFmpegPaths,
    captured: list[PatchRequest],
) -> None:
    def fake_patch(
        request: PatchRequest, *_args: Any, **_kwargs: Any
    ) -> SimpleNamespace:
        captured.append(request)
        return SimpleNamespace(output=request.src)

    monkeypatch.setattr("fps_patcher.cli.patch", fake_patch)
    monkeypatch.setattr("fps_patcher.cli.locate", lambda _custom=None: ff)


def test_cli_remediation_flags_reach_request_and_warn_once(
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    captured: list[PatchRequest] = []
    _bind_cli_fakes(monkeypatch, ff, captured)

    code = cli_main(
        [
            "patch",
            str(first),
            str(second),
            "--fix-vfr",
            "--fix-codec",
            "--cap-resolution",
        ],
        Settings(strategy="ffmpeg-copy"),
    )

    assert code == 0
    assert len(captured) == 2
    for request in captured:
        assert request.auto_fix_vfr is True
        assert request.auto_fix_codec is True
        assert request.auto_cap_resolution is True
    assert capsys.readouterr().err.splitlines() == [_LOSSY_WARNING]


def test_cli_no_remediation_warning_when_disabled(
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    captured: list[PatchRequest] = []
    _bind_cli_fakes(monkeypatch, ff, captured)

    code = cli_main(["patch", str(clip)], Settings())

    assert code == 0
    assert len(captured) == 1
    assert captured[0].auto_fix_vfr is False
    assert captured[0].auto_fix_codec is False
    assert captured[0].auto_cap_resolution is False
    assert capsys.readouterr().err == ""


def test_cli_settings_enabled_remediation_warns_and_applies(
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    captured: list[PatchRequest] = []
    _bind_cli_fakes(monkeypatch, ff, captured)

    code = cli_main(
        ["patch", str(clip)],
        Settings(auto_cap_resolution=True, strategy="ffmpeg-copy"),
    )

    assert code == 0
    assert len(captured) == 1
    assert captured[0].auto_cap_resolution is True
    assert capsys.readouterr().err.splitlines() == [_LOSSY_WARNING]


def test_cli_zilem_suppresses_preflight_warning(
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    captured: list[PatchRequest] = []
    _bind_cli_fakes(monkeypatch, ff, captured)

    code = cli_main(
        ["patch", str(clip), "--strategy", "zilem"],
        Settings(auto_fix_vfr=True, auto_fix_codec=True, auto_cap_resolution=True),
    )

    assert code == 0
    assert len(captured) == 1
    assert capsys.readouterr().err == ""


def test_cli_and_quick_patch_imports_stay_qt_free() -> None:
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'PySide6', 'shiboken6', 'tkinter', 'customtkinter'}:\n"
        "            raise ImportError('blocked ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import fps_patcher.cli\n"
        "import fps_patcher.app.quick_patch\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
