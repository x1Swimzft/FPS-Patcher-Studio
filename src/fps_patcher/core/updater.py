"""In-app updater: check GitHub Releases, download and verify, then launch the installer.

Standard library only. Network access is limited to HTTPS GitHub hosts, and a download
is refused when the release publishes a SHA-256 that does not match.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
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

ProgressCb = Callable[[int, int], None]


class UpdateError(PatchError):
    """Raised for any update check / download / verification failure."""


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


def _pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer the Windows installer, then any .exe, then a .zip."""

    def name(a: dict[str, Any]) -> str:
        return str(a.get("name", "")).lower()

    preds: tuple[Callable[[str], bool], ...] = (
        lambda n: n.endswith(".exe") and ("setup" in n or "install" in n),
        lambda n: n.endswith(".exe"),
        lambda n: n.endswith(".zip"),
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
                with _open(str(a["browser_download_url"]), timeout) as resp:
                    text = resp.read(4096).decode("utf-8", errors="replace")
            except (OSError, UpdateError):
                return None
            m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
            return m.group(1).lower() if m else None
    return None


def parse_release(data: dict[str, Any], timeout: float = 15) -> UpdateInfo:
    tag = str(data.get("tag_name", ""))
    assets = [a for a in data.get("assets", []) if isinstance(a, dict)]
    asset = _pick_asset(assets)
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


def check_for_update(current_version: str, timeout: float = 15) -> UpdateInfo | None:
    """Return release info when a newer version exists, else None. Raises UpdateError."""
    try:
        with _open(LATEST_URL, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no release published yet, not a failure
            exc.close()
            return None
        raise UpdateError(f"Update check failed: {exc}") from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Update check failed: {exc}") from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    info = parse_release(data, timeout)
    return info if is_newer(info.tag, current_version) else None


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    progress: ProgressCb | None = None,
    timeout: float = 30,
) -> Path:
    """Download the release asset into ``dest_dir`` and verify SHA-256 when published."""
    if not info.asset_url or not info.asset_name:
        raise UpdateError("This release has no downloadable installer asset.")
    safe_name = Path(info.asset_name).name  # never trust path parts from the API
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / safe_name
    part = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open(info.asset_url, timeout) as resp, part.open("wb") as fh:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            done = 0
            while chunk := resp.read(256 * 1024):
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (OSError, urllib.error.URLError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    if info.sha256 and digest.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("Downloaded file failed SHA-256 verification; it was deleted.")
    final.unlink(missing_ok=True)
    part.rename(final)
    return final


def launch_installer(path: Path) -> None:
    """Start the downloaded installer (Windows .exe) detached; caller then exits the app."""
    if sys.platform != "win32" or path.suffix.lower() != ".exe":
        raise UpdateError(f"Automatic install is only supported for Windows .exe: {path.name}")
    subprocess.Popen(  # noqa: S603 - path is a file we just verified and downloaded
        [str(path)],
        shell=False,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def default_download_dir() -> Path:
    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "FPSPatcherStudioUpdate"
