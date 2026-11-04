"""Windows login startup registration via the per-user Run key."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FPSPatcherStudio"


def startup_command() -> str:
    """Return the command Windows should run at sign-in, quoted for spaces."""
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}" --startup'
    pythonw = executable.with_name("pythonw.exe")
    runner = pythonw if pythonw.is_file() else executable
    return f'"{runner}" -m fps_patcher --startup'


def _winreg() -> Any:
    import winreg

    return winreg


def _read_command() -> str | None:
    if os.name != "nt":
        return None
    winreg = _winreg()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except (FileNotFoundError, OSError):
        return None


def set_startup_enabled(enabled: bool) -> bool:
    """Create or remove the HKCU Run entry. Returns False only on a real failure."""
    if os.name != "nt":
        return True
    winreg = _winreg()
    try:
        if enabled:
            command = startup_command()
            if _read_command() == command:
                return True
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
            return True
        if _read_command() is None:
            return True
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except OSError:
        return False
