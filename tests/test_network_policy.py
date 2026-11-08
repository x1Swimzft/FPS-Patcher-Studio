"""FFmpeg downloads are off by default; the app updater is independent of that policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings, ffmpeg_downloads_enabled
from fps_patcher.core.models import (
    FFmpegDownloadEvent,
    LogEvent,
    UpdateAvailableEvent,
    UpdateDownloadEvent,
)
from fps_patcher.core.updater import UpdateInfo


def _fake_update() -> UpdateInfo:
    return UpdateInfo(
        version="9.9.9",
        tag="v9.9.9",
        notes="Notes",
        page_url="https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/tag/v9.9.9",
        asset_name="FPSPatcherStudio-v9.9.9-Setup.exe",
        asset_url="https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v9.9.9/FPSPatcherStudio-v9.9.9-Setup.exe",
        asset_size=1000,
        sha256="a" * 64,
    )


def test_network_downloads_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    assert ffmpeg_downloads_enabled() is False

    ctrl = AppController(Settings())
    ctrl.start_ffmpeg_download()
    assert ctrl._ff_download is None

    events: list[object] = []
    ctrl.drain(events.append)
    assert any(isinstance(event, LogEvent) and "disabled" in event.message for event in events)
    assert any(
        isinstance(event, FFmpegDownloadEvent) and event.stage == "error" for event in events
    )


def test_update_check_runs_without_ffmpeg_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    info = _fake_update()
    monkeypatch.setattr("fps_patcher.core.updater.check_for_update", lambda _v: info)
    ctrl = AppController(Settings(check_updates_on_start=True))

    ctrl.check_for_updates_background("0.0.0")

    event = ctrl.events.get(timeout=2.0)
    assert isinstance(event, UpdateAvailableEvent)
    assert event.info == info


def test_update_download_runs_without_ffmpeg_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    info = _fake_update()
    expected = tmp_path / "Setup.exe"

    def fake_download(
        _info: Any, _dest: Path, progress: Any = None, cancel_event: Any = None
    ) -> Path:
        return expected

    monkeypatch.setattr("fps_patcher.core.updater.download_update", fake_download)
    ctrl = AppController(Settings())

    ctrl.start_update_download(info)

    worker = ctrl._update_worker
    assert worker is not None
    worker.join(timeout=2.0)
    event = ctrl.events.get(timeout=0.2)
    assert isinstance(event, UpdateDownloadEvent)
    assert event.stage == "done"
    assert event.path == expected
