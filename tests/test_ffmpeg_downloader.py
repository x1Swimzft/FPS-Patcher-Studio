"""Tests for FFmpeg downloader, extraction, verification, locator, and controller."""

from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from pathlib import Path
from types import TracebackType

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core.errors import FFmpegDownloadError
from fps_patcher.core.ffmpeg_downloader import download_ffmpeg
from fps_patcher.core.ffmpeg_locator import (
    FFmpegPaths,
    _exe,
    locate,
    managed_bin_dir,
)
from fps_patcher.core.models import (
    Event,
    FFmpegDownloadEvent,
    LogEvent,
)

FFMPEG_CONTENT = b"MZ-test-dummy-ffmpeg-content"
FFPROBE_CONTENT = b"MZ-test-dummy-ffprobe-content"
VERSION_STRING = "ffmpeg version test"


class FakeResponse:
    """Mock urllib context manager response for download streaming."""

    def __init__(self, data: bytes, content_length: int | None = None) -> None:
        self._bio = io.BytesIO(data)
        cl = len(data) if content_length is None else content_length
        self.headers = {"Content-Length": str(cl)}

    def read(self, n: int = -1) -> bytes:
        return self._bio.read(n)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


def build_zip_bytes(
    include_ffmpeg: bool = True,
    include_ffprobe: bool = True,
    ffmpeg_bytes: bytes = FFMPEG_CONTENT,
    ffprobe_bytes: bytes = FFPROBE_CONTENT,
    include_decoys: bool = True,
) -> bytes:
    """Build an in-memory zip archive with standard binaries and security decoys."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        prefix = "ffmpeg-master-latest-win64-gpl"
        if include_ffmpeg:
            zf.writestr(f"{prefix}/bin/ffmpeg.exe", ffmpeg_bytes)
        if include_ffprobe:
            zf.writestr(f"{prefix}/bin/ffprobe.exe", ffprobe_bytes)
        if include_decoys:
            zf.writestr(f"{prefix}/doc/ffmpeg.exe", b"decoy doc ffmpeg")
            zf.writestr(f"{prefix}/bin/ffplay.exe", b"decoy ffplay")
            zf.writestr("../../evil/bin/../ffmpeg.exe", b"traversal decoy 1")
            zf.writestr("../../bin/ffmpeg.exe", b"traversal decoy 2")
    return buf.getvalue()


@pytest.fixture
def mock_urlopen(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Mock urlopen and get_version for ffmpeg_downloader module."""
    zip_bytes = build_zip_bytes()

    def fake_urlopen(
        req: object,
        timeout: float | None = None,
        context: object = None,
        **kwargs: object,
    ) -> FakeResponse:
        return FakeResponse(zip_bytes)

    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.get_version",
        lambda _path: VERSION_STRING,
    )
    return zip_bytes


def test_download_ffmpeg_happy_path(tmp_path: Path, mock_urlopen: bytes) -> None:
    dest_dir = tmp_path / "bin"
    progress_records: list[tuple[int, int, str]] = []

    def cb(done: int, total: int, stage: str) -> None:
        progress_records.append((done, total, stage))

    paths = download_ffmpeg(dest_dir=dest_dir, progress=cb)

    assert paths.ffmpeg == dest_dir / "ffmpeg.exe"
    assert paths.ffprobe == dest_dir / "ffprobe.exe"
    assert paths.version == VERSION_STRING
    assert paths.ffmpeg.read_bytes() == FFMPEG_CONTENT
    assert paths.ffprobe.read_bytes() == FFPROBE_CONTENT

    # Cleanup checks: temporary zip and .staging must be gone
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()

    # Traversal decoys ignored, nothing written outside dest_dir
    assert set(dest_dir.iterdir()) == {dest_dir / "ffmpeg.exe", dest_dir / "ffprobe.exe"}
    assert set(tmp_path.iterdir()) == {dest_dir}

    # Progress monotonic and hits stages
    stages = [stage for _, _, stage in progress_records]
    assert "downloading" in stages
    assert "extracting" in stages
    assert "verifying" in stages

    downloading_dones = [done for done, _, stage in progress_records if stage == "downloading"]
    assert downloading_dones[0] == 0
    assert downloading_dones[-1] == len(mock_urlopen)
    assert downloading_dones == sorted(downloading_dones)


def test_download_ffmpeg_cancellation_preset(tmp_path: Path, mock_urlopen: bytes) -> None:
    dest_dir = tmp_path / "bin"
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(FFmpegDownloadError, match="cancelled"):
        download_ffmpeg(dest_dir=dest_dir, cancel=cancel)

    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_download_ffmpeg_cancellation_in_progress(tmp_path: Path, mock_urlopen: bytes) -> None:
    dest_dir = tmp_path / "bin"
    cancel = threading.Event()

    def cb(done: int, total: int, stage: str) -> None:
        cancel.set()

    with pytest.raises(FFmpegDownloadError, match="cancelled"):
        download_ffmpeg(dest_dir=dest_dir, progress=cb, cancel=cancel)

    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_download_ffmpeg_missing_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_dir = tmp_path / "bin"
    zip_bytes = build_zip_bytes(include_ffprobe=False)

    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(zip_bytes),
    )
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.get_version",
        lambda _path: VERSION_STRING,
    )

    with pytest.raises(FFmpegDownloadError, match="Archive missing: ffprobe.exe"):
        download_ffmpeg(dest_dir=dest_dir)

    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_download_ffmpeg_non_https(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_dir = tmp_path / "bin"
    urlopen_called = False

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal urlopen_called
        urlopen_called = True
        return FakeResponse(b"")

    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(FFmpegDownloadError, match="Refusing non-HTTPS"):
        download_ffmpeg(dest_dir=dest_dir, url="http://example.com/ffmpeg.zip")

    assert urlopen_called is False
    assert not (dest_dir / ".ffmpeg-download.zip").exists()


def test_download_ffmpeg_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_dir = tmp_path / "bin"
    zip_bytes = build_zip_bytes()

    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(zip_bytes),
    )
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.get_version",
        lambda _path: None,
    )

    with pytest.raises(FFmpegDownloadError, match="failed to run"):
        download_ffmpeg(dest_dir=dest_dir)

    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_download_ffmpeg_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_dir = tmp_path / "bin"
    zip_bytes = build_zip_bytes()

    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(zip_bytes, content_length=len(zip_bytes) + 1024),
    )
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_downloader.get_version",
        lambda _path: VERSION_STRING,
    )

    with pytest.raises(FFmpegDownloadError, match="Download incomplete"):
        download_ffmpeg(dest_dir=dest_dir)

    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_download_ffmpeg_sha256_verification_success(
    tmp_path: Path, mock_urlopen: bytes
) -> None:
    dest_dir = tmp_path / "bin"
    expected = hashlib.sha256(mock_urlopen).hexdigest()
    paths = download_ffmpeg(dest_dir=dest_dir, expected_sha256=expected)
    assert paths.ffmpeg.exists()
    assert paths.ffprobe.exists()


def test_download_ffmpeg_sha256_mismatch(
    tmp_path: Path, mock_urlopen: bytes
) -> None:
    dest_dir = tmp_path / "bin"
    wrong_hash = "0" * 64
    with pytest.raises(FFmpegDownloadError, match="Archive SHA-256 mismatch"):
        download_ffmpeg(dest_dir=dest_dir, expected_sha256=wrong_hash)
    assert not (dest_dir / "ffmpeg.exe").exists()
    assert not (dest_dir / "ffprobe.exe").exists()
    assert not (dest_dir / ".ffmpeg-download.zip").exists()
    assert not (dest_dir / ".staging").exists()


def test_ffmpeg_download_event_percent() -> None:
    assert FFmpegDownloadEvent("downloading", downloaded=0, total=0).percent == 0
    assert FFmpegDownloadEvent("downloading", downloaded=10, total=-5).percent == 0
    assert FFmpegDownloadEvent("downloading", downloaded=50, total=100).percent == 50
    assert FFmpegDownloadEvent("downloading", downloaded=100, total=100).percent == 100
    assert FFmpegDownloadEvent("downloading", downloaded=150, total=100).percent == 100
    assert FFmpegDownloadEvent("downloading", downloaded=-10, total=100).percent == 0


def test_managed_bin_dir_and_locate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_localappdata = tmp_path / "fake_local"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))

    expected_managed = fake_localappdata / "FPSPatcherStudio" / "bin"
    assert managed_bin_dir() == expected_managed

    expected_managed.mkdir(parents=True, exist_ok=True)
    fake_ffmpeg = expected_managed / _exe("ffmpeg")
    fake_ffprobe = expected_managed / _exe("ffprobe")
    fake_ffmpeg.write_bytes(b"dummy-ffmpeg")
    fake_ffprobe.write_bytes(b"dummy-ffprobe")

    monkeypatch.setattr("fps_patcher.core.ffmpeg_locator._bundled_bin_dirs", lambda: [])
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_locator.get_version",
        lambda p: "ffmpeg version 7.0-managed" if Path(p).is_file() else None,
    )

    paths = locate()
    assert paths.ffmpeg == fake_ffmpeg
    assert paths.ffprobe == fake_ffprobe
    assert paths.ffmpeg.parent == expected_managed
    assert paths.version == "ffmpeg version 7.0-managed"


def test_controller_ffmpeg_download_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_appdata = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_appdata))
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    fake_paths = FFmpegPaths(
        ffmpeg=tmp_path / "bin" / "ffmpeg.exe",
        ffprobe=tmp_path / "bin" / "ffprobe.exe",
        version="ffmpeg version controller-mock",
    )

    def fake_download_ffmpeg(
        dest_dir: Path | None = None,
        progress: object = None,
        cancel: object = None,
        url: str = "",
    ) -> FFmpegPaths:
        if callable(progress):
            progress(0, 100, "downloading")
            progress(100, 100, "downloading")
        return fake_paths

    monkeypatch.setattr(
        "fps_patcher.app.controller.download_ffmpeg",
        fake_download_ffmpeg,
    )
    monkeypatch.setattr(
        "fps_patcher.app.controller.locate",
        lambda custom_dir=None: fake_paths,
    )

    ctrl = AppController(Settings())
    assert ctrl.ffmpeg is None

    ctrl.start_ffmpeg_download()
    assert ctrl._ff_download is not None
    ctrl._ff_download.join(timeout=2.0)
    assert not ctrl._ff_download.is_alive()

    events: list[Event] = []
    ctrl.drain(events.append)

    done_evt = next(
        (e for e in events if isinstance(e, FFmpegDownloadEvent) and e.stage == "done"),
        None,
    )
    assert done_evt is not None
    assert done_evt.paths == fake_paths
    assert ctrl.ffmpeg == fake_paths


def test_controller_ffmpeg_download_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_appdata = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_appdata))
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    def fail_download(**kwargs: object) -> FFmpegPaths:
        raise FFmpegDownloadError("Simulated download failure")

    monkeypatch.setattr(
        "fps_patcher.app.controller.download_ffmpeg",
        fail_download,
    )

    ctrl = AppController(Settings())
    ctrl.start_ffmpeg_download()
    assert ctrl._ff_download is not None
    ctrl._ff_download.join(timeout=2.0)
    assert not ctrl._ff_download.is_alive()

    events: list[Event] = []
    ctrl.drain(events.append)

    err_evt = next(
        (e for e in events if isinstance(e, FFmpegDownloadEvent) and e.stage == "error"),
        None,
    )
    assert err_evt is not None
    assert err_evt.error is not None
    assert "Simulated download failure" in err_evt.error

    err_log = next(
        (e for e in events if isinstance(e, LogEvent) and e.level == "ERROR"),
        None,
    )
    assert err_log is not None
    assert "Simulated download failure" in err_log.message
    assert ctrl.ffmpeg is None
