"""In-app updater: check GitHub Releases, download and verify, then install or apply.

Standard library only. Network access is limited to HTTPS GitHub hosts, and a download
is refused when the release publishes a SHA-256 that does not match.

Installed copies run the Inno Setup installer; portable copies stage the zip and hand
the swap to a detached cmd trampoline that waits for the app to exit.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import PatchError

REPO = "x1Swimzft/FPS-Patcher-Studio"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
USER_AGENT = "FPSPatcherStudio-Updater"
ALLOW_UNSIGNED_ENV = "FPS_PATCHER_ALLOW_UNSIGNED_UPDATE"
MAX_EXTRACT_BYTES = 1024**3

ProgressCb = Callable[[int, int], None]

log = logging.getLogger(__name__)


class UpdateError(PatchError):
    """Raised for any update check / download / verification failure."""


class UpdateCancelledError(UpdateError):
    """Raised when the user cancels an update download."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_name: str | None
    asset_url: str | None
    asset_size: int
    sha256: str | None  # lowercase hex when the release publishes one


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.6.0' / '0.6.0-beta' -> (0, 6, 0). Non-numeric input -> ()."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text)
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def default_download_dir() -> Path:
    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "FPSPatcherStudioUpdate"


def detect_install_mode(app_dir: Path | None = None) -> str:
    """'installed' for an Inno Setup copy, else 'portable'. Dev runs are portable."""
    base = Path(sys.executable).resolve().parent if app_dir is None else app_dir
    return "installed" if (base / "unins000.exe").is_file() else "portable"


def _check_url(url: str) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_HOSTS:
        raise UpdateError(f"Refusing non-GitHub or non-HTTPS URL: {url}")


def _open(url: str, timeout: float) -> Any:
    _check_url(url)
    req = urllib.request.Request(  # noqa: S310 - scheme/host validated above
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


@contextmanager
def _open_checked(url: str, timeout: float) -> Iterator[Any]:
    """Close HTTPError responses, which urlopen raises instead of returning."""
    try:
        with _open(url, timeout) as resp:
            yield resp
    except urllib.error.HTTPError as exc:
        exc.close()
        raise


def _pick_asset(
    assets: list[dict[str, Any]], install_mode: str = "installed"
) -> dict[str, Any] | None:
    """Installed: Setup .exe, then any .exe. Portable: zip only."""

    def name(a: dict[str, Any]) -> str:
        return str(a.get("name", "")).lower()

    preds: tuple[Callable[[str], bool], ...]
    if install_mode == "portable":
        preds = (
            lambda n: n.endswith("-win64.zip"),
            lambda n: n.endswith(".zip"),
        )
    else:
        preds = (
            lambda n: n.endswith(".exe") and ("setup" in n or "install" in n),
            lambda n: n.endswith(".exe"),
        )
    for pred in preds:
        for a in assets:
            if pred(name(a)):
                return a
    return None


def _find_sha256(assets: list[dict[str, Any]], asset_name: str, timeout: float) -> str | None:
    wanted = {f"{asset_name}.sha256".lower(), f"{asset_name}.sha256sum".lower()}
    for a in assets:
        if str(a.get("name", "")).lower() in wanted and a.get("browser_download_url"):
            try:
                with _open_checked(str(a["browser_download_url"]), timeout) as resp:
                    text = resp.read(4096).decode("utf-8", errors="replace")
            except (OSError, UpdateError):
                return None
            m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
            return m.group(1).lower() if m else None
    return None


def parse_release(
    data: dict[str, Any], timeout: float = 15, install_mode: str | None = None
) -> UpdateInfo:
    mode = detect_install_mode() if install_mode is None else install_mode
    tag = str(data.get("tag_name", ""))
    assets = [a for a in data.get("assets", []) if isinstance(a, dict)]
    asset = _pick_asset(assets, mode)
    name = str(asset["name"]) if asset else None
    return UpdateInfo(
        version=".".join(str(p) for p in parse_version(tag)),
        tag=tag,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or f"https://github.com/{REPO}/releases"),
        asset_name=name,
        asset_url=str(asset["browser_download_url"]) if asset else None,
        asset_size=int(asset.get("size") or 0) if asset else 0,
        sha256=_find_sha256(assets, name, timeout) if name else None,
    )


def check_for_update(
    current_version: str, timeout: float = 15, install_mode: str | None = None
) -> UpdateInfo | None:
    """Return release info when a newer version exists, else None. Raises UpdateError."""
    try:
        with _open_checked(LATEST_URL, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no release published yet, not a failure
            return None
        raise UpdateError(f"Update check failed: {exc}") from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Update check failed: {exc}") from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    info = parse_release(data, timeout, install_mode)
    return info if is_newer(info.tag, current_version) else None


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    progress: ProgressCb | None = None,
    timeout: float = 30,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Download the release asset into ``dest_dir`` and verify SHA-256 when published."""
    if not info.asset_url or not info.asset_name:
        raise UpdateError("This release has no downloadable installer asset.")
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelledError("Update download cancelled.")
    safe_name = Path(info.asset_name).name  # never trust path parts from the API
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / safe_name
    part = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open_checked(info.asset_url, timeout) as resp, part.open("wb") as fh:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            done = 0
            while chunk := resp.read(256 * 1024):
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateCancelledError("Update download cancelled.")
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
            if cancel_event is not None and cancel_event.is_set():
                raise UpdateCancelledError("Update download cancelled.")
    except UpdateCancelledError:
        part.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    if total > 0 and done != total:
        part.unlink(missing_ok=True)
        raise UpdateError(
            f"Download incomplete: received {done} of {total} bytes; the file was deleted."
        )
    if info.sha256 and digest.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("Downloaded file failed SHA-256 verification; it was deleted.")
    final.unlink(missing_ok=True)
    part.rename(final)
    return final


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WinTrustFileInfo(ctypes.Structure):
    _fields_ = [
        ("cbStruct", ctypes.c_ulong),
        ("pcwszFilePath", ctypes.c_wchar_p),
        ("hFile", ctypes.c_void_p),
        ("pgKnownSubject", ctypes.c_void_p),
    ]


class _WinTrustData(ctypes.Structure):
    _fields_ = [
        ("cbStruct", ctypes.c_ulong),
        ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p),
        ("dwUIChoice", ctypes.c_ulong),
        ("fdwRevocationChecks", ctypes.c_ulong),
        ("dwUnionChoice", ctypes.c_ulong),
        ("pFile", ctypes.c_void_p),  # union: only the WINTRUST_FILE_INFO member is used
        ("dwStateAction", ctypes.c_ulong),
        ("hWVTStateData", ctypes.c_void_p),
        ("pwszURLReference", ctypes.c_wchar_p),
        ("dwProvFlags", ctypes.c_ulong),
        ("dwUIContext", ctypes.c_ulong),
        ("pSignatureSettings", ctypes.c_void_p),
    ]


# WINTRUST_ACTION_GENERIC_VERIFY_V2 {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
_ACTION_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B,
    0xCD44,
    0x11D0,
    (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
)
_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_CACHE_ONLY_URL_RETRIEVAL = 0x1000


def _wintrust() -> Any:
    dll = ctypes.WinDLL("wintrust.dll")
    fn = dll.WinVerifyTrust
    fn.restype = ctypes.c_long
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.c_void_p]
    return fn


def _winverifytrust(path: Path) -> int:
    """Call WinVerifyTrust for one file and always release its state data."""
    verify = _wintrust()
    file_info = _WinTrustFileInfo(
        cbStruct=ctypes.sizeof(_WinTrustFileInfo),
        pcwszFilePath=str(path),
    )
    data = _WinTrustData(
        cbStruct=ctypes.sizeof(_WinTrustData),
        dwUIChoice=_WTD_UI_NONE,
        fdwRevocationChecks=_WTD_REVOKE_NONE,
        dwUnionChoice=_WTD_CHOICE_FILE,
        pFile=ctypes.cast(ctypes.pointer(file_info), ctypes.c_void_p),
        dwStateAction=_WTD_STATEACTION_VERIFY,
        dwProvFlags=_WTD_CACHE_ONLY_URL_RETRIEVAL,
    )
    action = _ACTION_GENERIC_VERIFY_V2
    try:
        status = verify(None, ctypes.byref(action), ctypes.byref(data))
    finally:
        data.dwStateAction = _WTD_STATEACTION_CLOSE
        verify(None, ctypes.byref(action), ctypes.byref(data))
    return int(status)


def verify_authenticode(path: Path) -> None:
    """Verify a file's Authenticode signature; raise UpdateError when it is not trusted."""
    if sys.platform != "win32":
        raise UpdateError("Authenticode verification is only supported on Windows.")
    if os.environ.get(ALLOW_UNSIGNED_ENV) == "1":
        log.warning("Skipping Authenticode verification for %s (QA override).", path.name)
        return
    status = _winverifytrust(path)
    if status != 0:
        raise UpdateError(
            f"Authenticode signature verification failed for {path.name} "
            f"(0x{status & 0xFFFFFFFF:08X})."
        )


def launch_installer(
    path: Path, *, silent: bool = True, verify_signature: bool = True
) -> None:
    """Start the downloaded installer detached; caller then exits the app."""
    if sys.platform != "win32" or path.suffix.lower() != ".exe":
        raise UpdateError(f"Automatic install is only supported for Windows .exe: {path.name}")
    if verify_signature:
        verify_authenticode(path)
    args = [str(path)]
    if silent:
        args += ["/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        args,
        shell=False,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def apply_portable_update(
    zip_path: Path,
    *,
    app_dir: Path | None = None,
    pid: int | None = None,
    relaunch: bool = True,
    verify_signature: bool = True,
) -> Path:
    """Stage a portable zip and return the trampoline that applies it after exit."""
    base = default_download_dir()
    staging = base / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        root = staging.resolve()
        extracted = 0
        for member in archive.infolist():
            target = (staging / member.filename).resolve()
            if not target.is_relative_to(root):
                raise UpdateError(
                    f"Refusing unsafe path in update archive: {member.filename}"
                )
            extracted += member.file_size
            if extracted > MAX_EXTRACT_BYTES:
                raise UpdateError("Update archive exceeds the 1 GiB extraction limit.")
        archive.extractall(staging)

    # Compress-Archive wraps the app folder in a top-level FPSPatcherStudio/.
    source = staging / "FPSPatcherStudio"
    if not (source / "FPSPatcherStudio.exe").is_file():
        source = staging
    exe = source / "FPSPatcherStudio.exe"
    if not exe.is_file():
        raise UpdateError("Update archive does not contain FPSPatcherStudio.exe.")
    if verify_signature:
        verify_authenticode(exe)

    target_dir = (Path(sys.executable).resolve().parent if app_dir is None else app_dir).resolve()
    pid = os.getpid() if pid is None else pid
    lines = [
        "@echo off",
        "chcp 65001 >NUL",
        "setlocal",
        f'set "SRC={source}"',
        f'set "DST={target_dir}"',
        f'set "PID={pid}"',
        'set "WAITED=0"',
        ":wait",
        'tasklist /FI "PID eq %PID%" 2>NUL | findstr /C:"%PID%" >NUL',
        "if errorlevel 1 goto apply",
        "ping -n 2 127.0.0.1 >NUL",
        "set /a WAITED+=1",
        "if %WAITED% LSS 60 goto wait",
        ":apply",
    ]
    lines.append('robocopy "%SRC%" "%DST%" /E /MOVE /R:5 /W:1 /NFL /NDL /NJH /NJS')
    if relaunch:
        lines.append('start "" "%DST%\\FPSPatcherStudio.exe"')
    lines += [
        f'rmdir /s /q "{staging}" 2>NUL',
        'del "%~f0"',
    ]
    trampoline = base / "apply_update.cmd"
    trampoline.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    subprocess.Popen(  # noqa: S603 - fixed cmd.exe argv, no shell
        ["cmd.exe", "/c", str(trampoline)],
        shell=False,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return trampoline
