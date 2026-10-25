"""Per-user Explorer context menu registration (HKCU only, no admin).

The verb is registered under ``SystemFileAssociations`` so it applies to .mp4/.mov/.m4v
without taking over the default file association.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover - exercised on non-Windows CI only
    winreg = None  # type: ignore[assignment]

LABEL = "Quick Patch with X1T"
_KEY_ROOT = r"Software\Classes\SystemFileAssociations\{ext}\shell\FPSPatcherStudio"
_EXTENSIONS = (".mp4", ".mov", ".m4v")


class ShellIntegrationError(Exception):
    """Raised when the registry is unavailable or the key cannot be written."""


def _reg() -> Any:
    if winreg is None:
        raise ShellIntegrationError("Windows registry is not available on this platform.")
    return winreg


def application_executable() -> Path:
    """Frozen EXE, or the current interpreter (pythonw preferred) in source mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def quick_patch_command(exe: Path | None = None) -> str:
    exe = exe or application_executable()
    if getattr(sys, "frozen", False):
        return f'"{exe}" --quick-patch "%1"'
    return f'"{exe}" -m fps_patcher --quick-patch "%1"'


def _key_path(ext: str) -> str:
    return _KEY_ROOT.format(ext=ext)


def install(exe: Path | None = None) -> None:
    """Idempotently register the verb for .mp4, .mov and .m4v under HKCU."""
    reg = _reg()
    target = exe or application_executable()
    command = quick_patch_command(target)
    for ext in _EXTENSIONS:
        parent = _key_path(ext)
        key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, parent, 0, reg.KEY_WRITE)
        try:
            reg.SetValueEx(key, "", 0, reg.REG_SZ, LABEL)
            reg.SetValueEx(key, "Icon", 0, reg.REG_SZ, f'"{target}",0')
        finally:
            reg.CloseKey(key)
        command_key = reg.CreateKeyEx(
            reg.HKEY_CURRENT_USER, parent + r"\command", 0, reg.KEY_WRITE
        )
        try:
            reg.SetValueEx(command_key, "", 0, reg.REG_SZ, command)
        finally:
            reg.CloseKey(command_key)


def uninstall() -> None:
    """Remove the verb. Missing keys are ignored; other registry errors propagate."""
    reg = _reg()
    for ext in _EXTENSIONS:
        parent = _key_path(ext)
        for path in (parent + r"\command", parent):
            with contextlib.suppress(OSError):
                reg.DeleteKey(reg.HKEY_CURRENT_USER, path)


def is_installed() -> bool:
    reg = _reg()
    for ext in _EXTENSIONS:
        try:
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, _key_path(ext) + r"\command", 0, reg.KEY_READ)
        except OSError:
            return False
        try:
            value, _ = reg.QueryValueEx(key, "")
        finally:
            reg.CloseKey(key)
        if "--quick-patch" not in str(value):
            return False
    return True
