"""Phase 1 (v0.6.0): smart pre-flight planning and updater logic (no network/ffmpeg)."""

from __future__ import annotations

import hashlib
import urllib.error
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from fps_patcher.core import updater
from fps_patcher.core.models import VideoInfo
from fps_patcher.core.preflight import (
    PreflightPlan,
    build_preflight_args,
    encoder_candidates,
    make_plan,
    needs_audio_normalize,
    needs_bitrate_cap,
)


def _info(**kw: Any) -> VideoInfo:
    base: dict[str, Any] = {
        "path": Path("a.mp4"),
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "avg_fps": Fraction(60),
        "r_fps": Fraction(60),
        "duration_s": 10.0,
        "timescale": 60000,
        "nb_frames": 600,
        "has_audio": True,
        "stream_count": 2,
        "audio_codec": "aac",
        "bit_rate": 12_000_000,
        "audio_sample_rate": 48000,
        "audio_channels": 2,
    }
    base.update(kw)
    return VideoInfo(**base)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, False),
        ({"audio_codec": "pcm"}, True),
        ({"audio_codec": "alac"}, True),
        ({"audio_codec": "mp3"}, True),
        ({"audio_sample_rate": 44100}, True),
        ({"audio_channels": 1}, True),
        ({"audio_sample_rate": None, "audio_channels": None}, False),
        ({"has_audio": False, "audio_codec": None}, False),
    ],
)
def test_needs_audio_normalize(kw: dict[str, Any], expected: bool) -> None:
    assert needs_audio_normalize(_info(**kw)) is expected


def test_needs_bitrate_cap_threshold() -> None:
    assert not needs_bitrate_cap(_info(bit_rate=25_000_000))
    assert needs_bitrate_cap(_info(bit_rate=25_000_001))
    assert not needs_bitrate_cap(_info(bit_rate=None))


def test_make_plan_respects_toggles() -> None:
    info = _info(audio_codec="pcm", bit_rate=40_000_000)
    assert make_plan(info, normalize_audio=False, cap_bitrate=False) == PreflightPlan(False, False)
    assert make_plan(info, normalize_audio=True, cap_bitrate=False) == PreflightPlan(True, False)
    assert make_plan(info, normalize_audio=True, cap_bitrate=True) == PreflightPlan(True, True)


def test_audio_only_args_copy_video() -> None:
    args = build_preflight_args(Path("in.mov"), Path("out.mov"), PreflightPlan(True, False))
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-ar") + 1] == "48000"
    assert args[args.index("-ac") + 1] == "2"
    assert args[args.index("-b:a") + 1] == "192k"


def test_bitrate_cap_args_use_encoder_and_copy_good_audio() -> None:
    plan = PreflightPlan(False, True)
    args = build_preflight_args(Path("in.mp4"), Path("o.mp4"), plan, "h264_nvenc")
    assert args[args.index("-c:v") + 1] == "h264_nvenc"
    assert args[args.index("-maxrate") + 1] == "18M"
    assert args[args.index("-c:a") + 1] == "copy"


def test_encoder_candidates_order_and_fallback() -> None:
    assert encoder_candidates(["libx264", "h264_qsv", "h264_nvenc"]) == [
        "h264_nvenc",
        "h264_qsv",
        "libx264",
    ]
    assert encoder_candidates([]) == ["libx264"]


def test_version_compare() -> None:
    assert updater.is_newer("v0.6.0", "0.5.0")
    assert updater.is_newer("v1.0", "0.9.9")
    assert not updater.is_newer("v0.5.0", "0.5.0")
    assert not updater.is_newer("v0.4.9", "0.5.0")
    assert not updater.is_newer("nightly", "0.5.0")


def test_pick_asset_prefers_installer() -> None:
    assets = [
        {"name": "FPSPatcherStudio-0.6.0-portable.zip"},
        {"name": "FPSPatcherStudio-0.6.0-Setup.exe"},
    ]
    picked = updater._pick_asset(assets)
    assert picked is not None and picked["name"].endswith("Setup.exe")


def test_url_guard_rejects_foreign_hosts() -> None:
    with pytest.raises(updater.UpdateError):
        updater._check_url("http://github.com/x")
    with pytest.raises(updater.UpdateError):
        updater._check_url("https://evil.example.com/a.exe")
    updater._check_url("https://github.com/x1Swimzft/FPS-Patcher-Studio/releases")


def test_check_for_update_404_means_no_release(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", missing)
    assert updater.check_for_update("0.9.0") is None


def test_check_for_update_403_still_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", forbidden)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update("0.9.0")


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._p, self.headers = payload, {"Content-Length": str(len(payload))}

    def read(self, n: int = -1) -> bytes:
        out, self._p = self._p[:n], self._p[n:]
        return out

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


def _info_for(payload: bytes, sha: str | None) -> updater.UpdateInfo:
    return updater.UpdateInfo(
        "0.6.0", "v0.6.0", "", "https://github.com/x", "Setup.exe",
        "https://github.com/x/Setup.exe", len(payload), sha,
    )  # fmt: skip


def test_download_verifies_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"installer-bytes" * 1000
    monkeypatch.setattr(updater, "_open", lambda url, timeout: _FakeResp(data))
    out = updater.download_update(_info_for(data, hashlib.sha256(data).hexdigest()), tmp_path)
    assert out.read_bytes() == data
    assert not list(tmp_path.glob("*.part"))


def test_download_rejects_bad_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"tampered"
    monkeypatch.setattr(updater, "_open", lambda url, timeout: _FakeResp(data))
    with pytest.raises(updater.UpdateError):
        updater.download_update(_info_for(data, "0" * 64), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_e2e_pcm_mov_is_normalised_before_x1t(ff: Any, tmp_path: Path) -> None:
    """PCM audio in a .mov is converted to AAC 48k stereo; source stays untouched."""
    import subprocess

    from fps_patcher.core.models import PatchRequest
    from fps_patcher.core.patcher import patch
    from fps_patcher.core.prober import probe

    src = tmp_path / "clip.mov"
    subprocess.run(
        [
            str(ff.ffmpeg), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ac", "1",
            str(src),
        ],  # fmt: skip
        check=True,
    )
    before_bytes = src.read_bytes()
    assert needs_audio_normalize(probe(src, ff.ffprobe))

    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="x1t-mobile",
        auto_normalize_audio=True,
    )
    res = patch(req, ff, lambda _evt: None)

    after = probe(res.output, ff.ffprobe)
    assert after.audio_codec == "aac"
    assert after.audio_sample_rate == 48000
    assert after.audio_channels == 2
    assert src.read_bytes() == before_bytes
    assert not list(tmp_path.glob("*.preflight*"))


def test_preflight_cancel_leaves_no_partial_temp(
    clip30: Path, ff: Any, tmp_path: Path
) -> None:
    import shutil
    import threading

    from fps_patcher.core.errors import PatchCancelledError
    from fps_patcher.core.preflight import PreflightPlan, run_preflight

    src = tmp_path / clip30.name
    shutil.copy2(clip30, src)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(PatchCancelledError):
        run_preflight(
            src, PreflightPlan(normalize_audio=True, cap_bitrate=False), ff,
            lambda _evt: None, cancel,
        )

    assert not list(tmp_path.glob("*.preflight*"))
    assert not list(tmp_path.glob(".*.preflight-owner.json"))


def test_controller_check_for_updates_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from fps_patcher.app.controller import AppController
    from fps_patcher.config import Settings

    mock_check = MagicMock()
    monkeypatch.setattr("fps_patcher.core.updater.check_for_update", mock_check)
    settings = Settings(check_updates_on_start=False)
    ctrl = AppController(settings)

    ctrl.check_for_updates_background("0.5.0")
    mock_check.assert_not_called()
    assert ctrl.events.empty()


def test_controller_check_for_updates_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from fps_patcher.app.controller import AppController
    from fps_patcher.config import Settings
    from fps_patcher.core.models import UpdateAvailableEvent

    fake_info = updater.UpdateInfo(
        version="0.6.0",
        tag="v0.6.0",
        notes="Bug fixes",
        page_url="https://github.com/x",
        asset_name="Setup.exe",
        asset_url="https://github.com/x/Setup.exe",
        asset_size=1000,
        sha256=None,
    )
    mock_check = MagicMock(return_value=fake_info)
    monkeypatch.setattr("fps_patcher.core.updater.check_for_update", mock_check)
    settings = Settings(check_updates_on_start=True)
    ctrl = AppController(settings)

    ctrl.check_for_updates_background("0.5.0")
    event = ctrl.events.get(timeout=2.0)
    assert isinstance(event, UpdateAvailableEvent)
    assert event.info == fake_info
    mock_check.assert_called_once_with("0.5.0")


def test_controller_check_for_updates_handles_update_error_silently(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    import time

    from fps_patcher.app.controller import AppController
    from fps_patcher.config import Settings

    def raise_err(version: str) -> None:
        raise updater.UpdateError("Connection failed")

    monkeypatch.setattr("fps_patcher.core.updater.check_for_update", raise_err)
    settings = Settings(check_updates_on_start=True)
    ctrl = AppController(settings)

    with caplog.at_level(logging.DEBUG, logger="fps_patcher"):
        ctrl.check_for_updates_background("0.5.0")
        for _ in range(50):
            if any("Silent update check failed" in r.message for r in caplog.records):
                break
            time.sleep(0.01)

    assert any("Silent update check failed" in r.message for r in caplog.records)
    assert ctrl.events.empty()


def test_controller_start_update_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import contextlib
    import time

    from fps_patcher.app.controller import AppController
    from fps_patcher.config import Settings
    from fps_patcher.core.models import UpdateDownloadEvent

    fake_info = updater.UpdateInfo(
        version="0.6.0",
        tag="v0.6.0",
        notes="Notes",
        page_url="https://github.com/x",
        asset_name="Setup.exe",
        asset_url="https://github.com/x/Setup.exe",
        asset_size=1000,
        sha256=None,
    )
    expected_path = tmp_path / "Setup.exe"

    def mock_download(info: Any, dest: Path, progress: Any = None) -> Path:
        if progress:
            progress(500, 1000)
            progress(1000, 1000)
        return expected_path

    monkeypatch.setattr("fps_patcher.core.updater.download_update", mock_download)
    ctrl = AppController(Settings())

    ctrl.start_update_download(fake_info)

    events: list[Any] = []
    end = time.time() + 2.0
    while time.time() < end and len(events) < 3:
        with contextlib.suppress(Exception):
            events.append(ctrl.events.get(timeout=0.1))

    downloading = [
        e for e in events if isinstance(e, UpdateDownloadEvent) and e.stage == "downloading"
    ]
    assert len(downloading) == 2
    assert downloading[0].downloaded == 500
    assert downloading[0].total == 1000
    assert downloading[0].percent == 50
    assert downloading[1].percent == 100

    done = [e for e in events if isinstance(e, UpdateDownloadEvent) and e.stage == "done"]
    assert len(done) == 1
    assert done[0].path == expected_path


def test_controller_start_update_download_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from fps_patcher.app.controller import AppController
    from fps_patcher.config import Settings
    from fps_patcher.core.models import UpdateDownloadEvent

    def mock_download_fail(info: Any, dest: Path, progress: Any = None) -> Path:
        raise updater.UpdateError("SHA-256 verification failed")

    monkeypatch.setattr("fps_patcher.core.updater.download_update", mock_download_fail)
    ctrl = AppController(Settings())

    ctrl.start_update_download(MagicMock())
    event = ctrl.events.get(timeout=2.0)
    assert isinstance(event, UpdateDownloadEvent)
    assert event.stage == "error"
    assert "SHA-256 verification failed" in (event.error or "")
