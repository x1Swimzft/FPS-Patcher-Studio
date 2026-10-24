"""Best-effort Windows toast notifications through PowerShell WinRT.

No third-party dependency and no user text interpolation: the title and body are
passed through environment variables, so quotes/newlines cannot break the script.
Failures are deliberately non-fatal; notifications are cosmetic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .. import APP_NAME, APP_USER_MODEL_ID

_CREATE_NO_WINDOW = 0x08000000

# Static script. Do not add f-strings or user input here.
_TOAST_SCRIPT = "\n".join(
    (
        r"$ErrorActionPreference = 'Stop'",
        r"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        r"ContentType = WindowsRuntime] | Out-Null",
        r"$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02",
        r"$xml = [Windows.UI.Notifications.ToastNotificationManager]"
        r"::GetTemplateContent($template)",
        r"$texts = $xml.GetElementsByTagName('text')",
        r"$texts.Item(0).AppendChild($xml.CreateTextNode($env:FPS_TOAST_TITLE)) | Out-Null",
        r"$texts.Item(1).AppendChild($xml.CreateTextNode($env:FPS_TOAST_BODY)) | Out-Null",
        r"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)",
        r"[Windows.UI.Notifications.ToastNotificationManager]"
        r"::CreateToastNotifier($env:FPS_TOAST_APP_ID).Show($toast)",
    )
)


def toast(
    message: str,
    *,
    title: str = APP_NAME,
    app_id: str = APP_USER_MODEL_ID,
    timeout_s: float = 10.0,
) -> bool:
    """Show a Windows toast. Returns False on any non-Windows/failed attempt."""
    if sys.platform != "win32":
        return False

    powershell = shutil.which("powershell.exe") or "powershell.exe"
    env = os.environ.copy()
    env["FPS_TOAST_TITLE"] = title[:120]
    env["FPS_TOAST_BODY"] = message[:512]
    env["FPS_TOAST_APP_ID"] = app_id

    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _TOAST_SCRIPT,
            ],
            env=env,
            capture_output=True,
            timeout=timeout_s,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
