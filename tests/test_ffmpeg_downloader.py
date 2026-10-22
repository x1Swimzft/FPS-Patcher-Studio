"""Tests for FFmpeg downloader, extraction, verification, locator, and controller."""

from __future__ import annotations

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


def test_ffmpeg_tab_ui_download_event_lifecycle() -> None:
    from unittest.mock import MagicMock

    import customtkinter as ctk

    from fps_patcher.ui.settings_tabs.ffmpeg import FFmpegTab
    from fps_patcher.ui.theme import get_theme_manager

    root = ctk.CTk()
    root.withdraw()
    try:
        dialog = MagicMock()
        ctrl = MagicMock()
        ctrl.ffmpeg_downloading = False
        dialog.controller = ctrl
        dialog._draft = Settings()
        dialog._theme_mgr = get_theme_manager(dialog._draft)
        dialog._tr = lambda key, **kwargs: f"{key}_{kwargs}" if kwargs else key

        parent = ctk.CTkFrame(root)
        tab = FFmpegTab(parent, dialog)

        # 1. Initial state: progress bar not mapped, button normal
        assert tab.download_btn.cget("state") == "normal"
        assert not tab._progress_visible
        assert tab.download_progress.get() == 0

        # 2. Start download
        tab._start_download()
        assert ctrl.start_ffmpeg_download.called
        assert tab.download_btn.cget("state") == "disabled"
        assert tab._progress_visible
        assert tab.download_progress.winfo_manager() == "pack"

        # 3. Downloading event
        evt_dl = FFmpegDownloadEvent("downloading", downloaded=50, total=100)
        tab.on_download_event(evt_dl)
        assert tab.download_btn.cget("state") == "disabled"
        assert round(tab.download_progress.get(), 2) == 0.5
        assert "50" in tab.download_status.cget("text")

        # 4. Extracting event
        evt_ext = FFmpegDownloadEvent("extracting")
        tab.on_download_event(evt_ext)
        assert tab.download_btn.cget("state") == "disabled"
        assert "ffmpeg_extracting" in tab.download_status.cget("text")

        # 5. Done event
        fake_paths = FFmpegPaths(
            ffmpeg=Path("/fake/bin/ffmpeg.exe"),
            ffprobe=Path("/fake/bin/ffprobe.exe"),
            version="ffmpeg version 7.0-test",
        )
        evt_done = FFmpegDownloadEvent("done", paths=fake_paths)
        tab.on_download_event(evt_done)
        assert tab.download_btn.cget("state") == "normal"
        assert tab.download_progress.get() == 1.0
        assert "ffmpeg_installed" in tab.download_status.cget("text")
        assert tab.ff_dir_entry.get() == str(Path("/fake/bin"))
        assert "✔ ffmpeg version 7.0-test" in tab.ff_test_res.cget("text")

        # 6. Error event
        evt_err = FFmpegDownloadEvent("error", error="Network error")
        tab.on_download_event(evt_err)
        assert tab.download_btn.cget("state") == "normal"
        assert "Network error" in tab.download_status.cget("text")
    finally:
        root.destroy()


def test_main_window_ffmpeg_badge_click_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock, patch

    from fps_patcher.ui.main_window import MainWindow
    from fps_patcher.ui.theme import get_theme_manager

    with patch("fps_patcher.ui.main_window.font_badge", return_value=None):
        w = MainWindow.__new__(MainWindow)
        w.settings = Settings()
        w.controller = MagicMock()
        w.console = MagicMock()
        w.ff_badge = MagicMock()
        mock_pick = MagicMock()
        mock_refresh = MagicMock()
        mock_probe = MagicMock()
        monkeypatch.setattr(w, "_pick_ffmpeg", mock_pick)
        monkeypatch.setattr(w, "_refresh_state", mock_refresh)
        monkeypatch.setattr(w, "_probe_pending_queue_items", mock_probe)
        w._theme_mgr = get_theme_manager(w.settings)
        w._ff_state = "not_found"
        w._ff_download_text = ""
        w._settings_win = None

        # Not found -> click starts download
        w._on_ff_badge_click()
        assert w.controller.start_ffmpeg_download.call_count == 1
        assert mock_pick.call_count == 0

        # Downloading -> click is no-op
        w._ff_state = "downloading"
        w._on_ff_badge_click()
        assert w.controller.start_ffmpeg_download.call_count == 1
        assert mock_pick.call_count == 0

        # Ready -> click picks ffmpeg
        w._ff_state = "ready"
        w._on_ff_badge_click()
        assert mock_pick.call_count == 1

        # Style checks
        w._ff_state = "not_found"
        w._apply_ff_badge_style(w._theme_mgr.tokens)
        badge_text = w.ff_badge.configure.call_args.kwargs["text"]
        assert "Download FFmpeg" in badge_text

        w._ff_state = "downloading"
        w._ff_download_text = "Downloading FFmpeg (30%)..."
        w._apply_ff_badge_style(w._theme_mgr.tokens)
        assert w.ff_badge.configure.call_args.kwargs["text"] == "Downloading FFmpeg (30%)..."

        # Event handling in _handle
        mock_settings_win = MagicMock()
        mock_settings_win.winfo_exists.return_value = True
        w._settings_win = mock_settings_win

        evt_dl = FFmpegDownloadEvent("downloading", downloaded=40, total=100)
        w._handle(evt_dl)
        assert w._ff_state == "downloading"
        assert "40%" in w._ff_download_text
        mock_settings_win.tab_ffmpeg.on_download_event.assert_called_with(evt_dl)

        evt_ext = FFmpegDownloadEvent("extracting")
        w._handle(evt_ext)
        assert w._ff_state == "downloading"
        assert "Extracting" in w._ff_download_text
        mock_settings_win.tab_ffmpeg.on_download_event.assert_called_with(evt_ext)

        fake_paths = FFmpegPaths(
            ffmpeg=Path("/fake/bin/ffmpeg.exe"),
            ffprobe=Path("/fake/bin/ffprobe.exe"),
            version="ffmpeg version 7.0-test",
        )
        evt_done = FFmpegDownloadEvent("done", paths=fake_paths)
        w._handle(evt_done)
        assert w._ff_state == "ready"
        assert mock_refresh.called
        assert mock_probe.called
        assert w.console.append.called
        mock_settings_win.tab_ffmpeg.on_download_event.assert_called_with(evt_done)

        evt_err = FFmpegDownloadEvent("error", error="Fail")
        w._handle(evt_err)
        assert w._ff_state == "not_found"
        mock_settings_win.tab_ffmpeg.on_download_event.assert_called_with(evt_err)
