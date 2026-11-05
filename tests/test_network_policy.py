"""Network downloads are off unless the explicit environment override is set."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings, network_downloads_enabled
from fps_patcher.core.models import FFmpegDownloadEvent, LogEvent, UpdateDownloadEvent


def test_network_downloads_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    assert network_downloads_enabled() is False

    ctrl = AppController(Settings())
    ctrl.start_ffmpeg_download()
    assert ctrl._ff_download is None

    events: list[object] = []
    ctrl.drain(events.append)
    assert any(isinstance(event, LogEvent) and "disabled" in event.message for event in events)
    assert any(
        isinstance(event, FFmpegDownloadEvent) and event.stage == "error" for event in events
    )


def test_network_downloads_off_blocks_update_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    ctrl = AppController(Settings(check_updates_on_start=True))

    ctrl.check_for_updates_background("0.0.0")
    assert ctrl.events.empty()

    ctrl.start_update_download(MagicMock())
    event = ctrl.events.get(timeout=1.0)
    assert isinstance(event, UpdateDownloadEvent)
    assert event.stage == "error"
    assert "disabled" in (event.error or "")
