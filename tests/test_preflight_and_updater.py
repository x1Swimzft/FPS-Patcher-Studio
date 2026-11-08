"""Phase 1 (v0.6.0): smart pre-flight planning and updater logic (no network/ffmpeg)."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import threading
import urllib.error
import zipfile
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
    planned_output_bitrate,
    target_bitrate_bps,
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


def test_needs_bitrate_cap_uses_target() -> None:
    assert not needs_bitrate_cap(_info(bit_rate=16_000_000))
    assert needs_bitrate_cap(_info(bit_rate=16_000_001))
    assert not needs_bitrate_cap(_info(bit_rate=20_000_000), target_bps=25_000_000)
    assert not needs_bitrate_cap(_info(bit_rate=None))


def test_planned_output_bitrate_follows_cap_target() -> None:
    high = _info(bit_rate=40_000_000)
    low = _info(bit_rate=12_000_000)
    assert planned_output_bitrate(high, cap_bitrate=True, target_mbps=12) == 12_000_000
    assert planned_output_bitrate(high, cap_bitrate=False, target_mbps=12) == 40_000_000
    assert planned_output_bitrate(low, cap_bitrate=True, target_mbps=16) == 12_000_000
    assert planned_output_bitrate(_info(bit_rate=None), cap_bitrate=True) is None


def test_target_bitrate_is_clamped() -> None:
    assert target_bitrate_bps(0) == 1_000_000
    assert target_bitrate_bps(99) == 24_000_000


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


def test_bitrate_cap_args_use_custom_target() -> None:
    plan = PreflightPlan(False, True)
    args = build_preflight_args(
        Path("in.mp4"), Path("o.mp4"), plan, "libx264", bitrate_target_mbps=10
    )
    assert args[args.index("-b:v") + 1] == "10M"
    assert args[args.index("-maxrate") + 1] == "12M"
    assert args[args.index("-bufsize") + 1] == "20M"


def test_bitrate_cap_args_try_hardware_decode_before_input() -> None:
    plan = PreflightPlan(False, True)
    args = build_preflight_args(
        Path("in.mp4"), Path("o.mp4"), plan, "h264_nvenc", hwaccel="d3d11va"
    )
    assert args.index("-hwaccel") < args.index("-i")
    assert args[args.index("-hwaccel") + 1] == "d3d11va"


def test_audio_only_args_ignore_hardware_decode() -> None:
    args = build_preflight_args(
        Path("in.mov"), Path("out.mov"), PreflightPlan(True, False), hwaccel="d3d11va"
    )
    assert "-hwaccel" not in args


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
    fp = io.BytesIO(b"not found")

    def missing(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, fp)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", missing)
    assert updater.check_for_update("0.9.0") is None
    assert fp.closed


@pytest.mark.parametrize("code", [403, 500])
def test_check_for_update_http_error_is_closed(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    fp = io.BytesIO(b"error body")

    def failing(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, code, "Error", {}, fp)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", failing)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update("0.9.0")
    assert fp.closed


def test_check_for_update_timeout_is_an_update_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(url: str, timeout: float) -> Any:
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(updater, "_open", slow)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update("0.9.0")


class _FakeResp:
    def __init__(self, payload: bytes, error: BaseException | None = None) -> None:
        self._p, self.headers = payload, {"Content-Length": str(len(payload))}
        self._error = error
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        if self._error is not None:
            raise self._error
        out, self._p = self._p[:n], self._p[n:]
        return out

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *a: object) -> None:
        self.closed = True


def _info_for(payload: bytes, sha: str | None) -> updater.UpdateInfo:
    return updater.UpdateInfo(
        "0.6.0", "v0.6.0", "", "https://github.com/x", "Setup.exe",
        "https://github.com/x/Setup.exe", len(payload), sha,
    )  # fmt: skip


def test_check_for_update_read_timeout_closes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _FakeResp(b"", error=TimeoutError("timed out while reading"))
    monkeypatch.setattr(updater, "_open", lambda url, timeout: resp)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update("0.9.0")
    assert resp.closed


def test_download_read_timeout_closes_response_and_removes_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = _FakeResp(b"", error=TimeoutError("timed out while reading"))
    monkeypatch.setattr(updater, "_open", lambda url, timeout: resp)
    with pytest.raises(updater.UpdateError):
        updater.download_update(_info_for(b"x", None), tmp_path)
    assert resp.closed
    assert list(tmp_path.iterdir()) == []


def test_download_verifies_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"installer-bytes" * 1000
    monkeypatch.setattr(updater, "_open", lambda url, timeout: _FakeResp(data))
    out = updater.download_update(_info_for(data, hashlib.sha256(data).hexdigest()), tmp_path)
    assert out.read_bytes() == data
    assert not list(tmp_path.glob("*.part"))


def test_download_closes_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fp = io.BytesIO(b"forbidden")

    def failing(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, fp)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", failing)
    with pytest.raises(updater.UpdateError):
        updater.download_update(_info_for(b"x", None), tmp_path)
    assert fp.closed
    assert list(tmp_path.iterdir()) == []


def test_sha_lookup_closes_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fp = io.BytesIO(b"forbidden")

    def failing(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, fp)  # type: ignore[arg-type]

    monkeypatch.setattr(updater, "_open", failing)
    assets = [
        {"name": "Setup.exe.sha256", "browser_download_url": "https://github.com/x/sha"}
    ]
    assert updater._find_sha256(assets, "Setup.exe", 1) is None
    assert fp.closed


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


def test_update_check_enabled_by_default() -> None:
    from fps_patcher.config import Settings

    assert Settings().check_updates_on_start is True


def test_legacy_settings_enable_updates_once() -> None:
    from fps_patcher.config import Settings

    settings = Settings(check_updates_on_start=False, updates_default_migrated=False)
    settings._clamp()
    assert settings.check_updates_on_start is True
    assert settings.updates_default_migrated is True

    settings.check_updates_on_start = False
    settings._clamp()
    assert settings.check_updates_on_start is False


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

    def mock_download(
        info: Any, dest: Path, progress: Any = None, cancel_event: Any = None
    ) -> Path:
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

    def mock_download_fail(
        info: Any, dest: Path, progress: Any = None, cancel_event: Any = None
    ) -> Path:
        raise updater.UpdateError("SHA-256 verification failed")

    monkeypatch.setattr("fps_patcher.core.updater.download_update", mock_download_fail)
    ctrl = AppController(Settings())

    ctrl.start_update_download(MagicMock())
    event = ctrl.events.get(timeout=2.0)
    assert isinstance(event, UpdateDownloadEvent)
    assert event.stage == "error"
    assert "SHA-256 verification failed" in (event.error or "")


# --- v1.3.1: portable updates, cancellation, Authenticode and trampoline


def test_detect_install_mode_installed_vs_portable(tmp_path: Path) -> None:
    assert updater.detect_install_mode(tmp_path) == "portable"
    (tmp_path / "unins000.exe").write_bytes(b"MZ")
    assert updater.detect_install_mode(tmp_path) == "installed"


def test_pick_asset_portable_uses_zip_only() -> None:
    assets = [
        {"name": "FPSPatcherStudio-v1.3.1-Setup.exe"},
        {"name": "FPSPatcherStudio-v1.3.1-win64.zip"},
    ]
    picked = updater._pick_asset(assets, "portable")
    assert picked is not None and picked["name"].endswith("-win64.zip")
    assert updater._pick_asset([{"name": "FPSPatcherStudio-v1.3.1-Setup.exe"}], "portable") is None


def test_pick_asset_installed_never_falls_back_to_zip() -> None:
    assets = [{"name": "FPSPatcherStudio-v1.3.1-win64.zip"}]
    assert updater._pick_asset(assets, "installed") is None


def test_download_cancel_closes_response_and_removes_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    resp = _FakeResp(b"partial" * 100)

    def cancelling_open(url: str, timeout: float) -> _FakeResp:
        cancel.set()
        return resp

    monkeypatch.setattr(updater, "_open", cancelling_open)
    with pytest.raises(updater.UpdateCancelledError):
        updater.download_update(_info_for(b"x", None), tmp_path, cancel_event=cancel)
    assert resp.closed
    assert list(tmp_path.iterdir()) == []


def test_download_truncated_stream_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = _FakeResp(b"short")
    resp.headers["Content-Length"] = "4096"
    monkeypatch.setattr(updater, "_open", lambda url, timeout: resp)
    with pytest.raises(updater.UpdateError, match="Download incomplete"):
        updater.download_update(_info_for(b"x" * 4096, None), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_verify_authenticode_accepts_valid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_winverifytrust", lambda path: 0)
    updater.verify_authenticode(Path("FPSPatcherStudio.exe"))


def test_verify_authenticode_rejects_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_winverifytrust", lambda path: 0x800B0100)
    with pytest.raises(updater.UpdateError, match=r"0x800B0100"):
        updater.verify_authenticode(Path("FPSPatcherStudio.exe"))


def test_verify_authenticode_env_override_skips_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("FPS_PATCHER_ALLOW_UNSIGNED_UPDATE", "1")
    monkeypatch.setattr(updater, "_winverifytrust", lambda path: 0x800B0100)
    updater.verify_authenticode(Path("FPSPatcherStudio.exe"))


def test_launch_installer_silent_flags_and_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified: list[Path] = []
    spawned: list[tuple[list[str], dict[str, Any]]] = []

    def fake_verify(path: Path) -> None:
        verified.append(path)

    def fake_popen(args: list[str], **kwargs: Any) -> None:
        spawned.append((args, kwargs))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "verify_authenticode", fake_verify)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    installer = Path("C:/Temp/FPSPatcherStudio-Setup.exe")

    updater.launch_installer(installer)

    assert verified == [installer]
    args, kwargs = spawned[0]
    assert args == [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
    assert kwargs["shell"] is False
    assert kwargs["close_fds"] is True


def test_apply_portable_update_stages_zip_and_writes_trampoline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zip_path = tmp_path / "FPSPatcherStudio-v1.3.1-win64.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("FPSPatcherStudio/FPSPatcherStudio.exe", b"MZ")
        archive.writestr("FPSPatcherStudio/README.md", b"readme")

    download_dir = tmp_path / "downloads"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    spawned: list[list[str]] = []

    def fake_popen(args: list[str], **kwargs: Any) -> None:
        spawned.append(args)

    monkeypatch.setattr(updater, "default_download_dir", lambda: download_dir)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    trampoline = updater.apply_portable_update(
        zip_path, app_dir=app_dir, pid=4321, verify_signature=False
    )

    staging = download_dir / "staging"
    assert (staging / "FPSPatcherStudio" / "FPSPatcherStudio.exe").read_bytes() == b"MZ"
    assert trampoline == download_dir / "apply_update.cmd"
    script = trampoline.read_text(encoding="utf-8")
    assert 'robocopy "%SRC%" "%DST%" /E /MOVE /R:5 /W:1 /NFL /NDL /NJH /NJS' in script
    assert "PID eq %PID%" in script
    assert "4321" in script
    assert 'start "" "%DST%\\FPSPatcherStudio.exe"' in script
    assert f'rmdir /s /q "{staging}" 2>NUL' in script
    assert spawned == [["cmd.exe", "/c", str(trampoline)]]


def test_apply_portable_update_defaults_to_current_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zip_path = tmp_path / "FPSPatcherStudio-win64.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("FPSPatcherStudio/FPSPatcherStudio.exe", b"MZ")

    download_dir = tmp_path / "downloads"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(updater, "default_download_dir", lambda: download_dir)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: None)

    trampoline = updater.apply_portable_update(
        zip_path, app_dir=app_dir, verify_signature=False
    )

    script = trampoline.read_text(encoding="utf-8")
    assert f'set "PID={os.getpid()}"' in script
    assert ":wait" in script
    assert script.index(":wait") < script.index("robocopy")


def test_apply_portable_update_rejects_zip_slip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../evil.exe", b"MZ")

    download_dir = tmp_path / "downloads"
    monkeypatch.setattr(updater, "default_download_dir", lambda: download_dir)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not spawn")
    )

    with pytest.raises(updater.UpdateError, match="unsafe path"):
        updater.apply_portable_update(
            zip_path, app_dir=tmp_path / "app", verify_signature=False
        )
    assert not (download_dir / "evil.exe").exists()
    assert not (tmp_path / "evil.exe").exists()
