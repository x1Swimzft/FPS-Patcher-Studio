"""Qt UI: readiness auto-fix action and the opt-in lossy remediation switches."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton  # noqa: E402

from fps_patcher import config  # noqa: E402
from fps_patcher.app.queue_model import QueueItem  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.models import VideoInfo  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import inspector as inspector_module  # noqa: E402
from fps_patcher.ui_qt.inspector import Inspector  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


def _info(path: Path) -> VideoInfo:
    return VideoInfo(
        path=path,
        codec="h264",
        width=1080,
        height=1920,
        avg_fps=Fraction(30),
        r_fps=Fraction(30),
        duration_s=10.0,
        timescale=30000,
        nb_frames=300,
        has_audio=True,
        stream_count=2,
    )


def _inspector(qtbot: Any, settings: Settings) -> Inspector:
    inspector = Inspector(settings, ThemeManager(settings))
    qtbot.addWidget(inspector)
    inspector.show()
    return inspector


def _focus(qtbot: Any, settings: Settings, tmp_path: Path) -> tuple[Inspector, QueueItem]:
    inspector = _inspector(qtbot, settings)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    item = QueueItem(path=video, info=_info(video))
    inspector.set_focused_item(item)
    return inspector, item


def _remediate_button(inspector: Inspector) -> QPushButton | None:
    popover = inspector._popover
    assert popover is not None
    return popover.findChild(QPushButton, "remediate_button")


def _wait_until_saved(qtbot: Any, path: Path, field: str) -> None:
    def saved() -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get(field))

    qtbot.waitUntil(saved, timeout=3000)


def test_popover_shows_auto_fix_button_only_for_remediable_failures(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    settings = Settings(reduce_motion=True)
    inspector, _item = _focus(qtbot, settings, tmp_path)

    monkeypatch.setattr(inspector_module, "remediable_checks", lambda report: ("audio",))
    inspector._open_readiness()
    button = _remediate_button(inspector)
    assert button is not None
    assert button.text() == t("remediate_btn", "en")

    monkeypatch.setattr(inspector_module, "remediable_checks", lambda report: ())
    inspector._open_readiness()
    assert _remediate_button(inspector) is None


def test_auto_fix_yes_sets_only_failed_flags_and_persists(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(config, "app_data_dir", lambda: appdata)
    settings = Settings(reduce_motion=True)
    inspector, _item = _focus(qtbot, settings, tmp_path)
    monkeypatch.setattr(
        inspector_module, "remediable_checks", lambda report: ("frame_rate", "video_codec")
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        MagicMock(return_value=QMessageBox.StandardButton.Yes),
    )

    inspector._open_readiness()
    button = _remediate_button(inspector)
    assert button is not None
    button.click()

    assert settings.auto_fix_vfr is True
    assert settings.auto_fix_codec is True
    assert settings.auto_cap_resolution is False
    assert settings.auto_cap_bitrate is False
    assert settings.auto_normalize_audio is True
    assert inspector._popover is None
    assert inspector.readiness_label.text() == t("remediate_done", "en")

    path = appdata / "settings.json"
    _wait_until_saved(qtbot, path, "auto_fix_vfr")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["auto_fix_vfr"] is True
    assert saved["auto_fix_codec"] is True
    assert saved["auto_cap_resolution"] is False


def test_auto_fix_no_changes_nothing(qtbot: Any, monkeypatch: Any, tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(config, "app_data_dir", lambda: appdata)
    settings = Settings(reduce_motion=True)
    inspector, _item = _focus(qtbot, settings, tmp_path)
    monkeypatch.setattr(inspector_module, "remediable_checks", lambda report: ("frame_rate",))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        MagicMock(return_value=QMessageBox.StandardButton.No),
    )

    inspector._open_readiness()
    button = _remediate_button(inspector)
    assert button is not None
    button.click()

    assert settings.auto_fix_vfr is False
    assert settings.auto_fix_codec is False
    assert settings.auto_cap_resolution is False
    assert inspector._popover is not None
    assert not (appdata / "settings.json").exists()


def test_audio_only_failure_skips_lossy_video_confirmation(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(config, "app_data_dir", lambda: appdata)
    settings = Settings(reduce_motion=True)
    inspector, _item = _focus(qtbot, settings, tmp_path)
    monkeypatch.setattr(inspector_module, "remediable_checks", lambda report: ("audio",))
    warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", warning)

    inspector._open_readiness()
    button = _remediate_button(inspector)
    assert button is not None
    button.click()

    warning.assert_not_called()
    assert settings.auto_normalize_audio is True
    assert settings.auto_fix_vfr is False
    _wait_until_saved(qtbot, appdata / "settings.json", "auto_normalize_audio")


def test_video_failure_shows_lossy_confirmation(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    settings = Settings(reduce_motion=True)
    inspector, _item = _focus(qtbot, settings, tmp_path)
    monkeypatch.setattr(inspector_module, "remediable_checks", lambda report: ("frame_rate",))
    warning = MagicMock(return_value=QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", warning)

    inspector._open_readiness()
    button = _remediate_button(inspector)
    assert button is not None
    button.click()

    warning.assert_called_once()
    assert "H.264" in warning.call_args.args[2]


def test_readiness_badge_uses_item_profile_override(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    settings = Settings(reduce_motion=True, platform_profile="youtube")
    inspector, item = _focus(qtbot, settings, tmp_path)
    item.platform_profile = "tiktok"
    inspector.refresh_readiness()
    report = inspector._report
    assert report is not None
    assert report.profile_id == "tiktok"

    inspector._open_readiness()
    popover = inspector._popover
    assert popover is not None
    expected = t(
        "readiness_badge",
        "en",
        profile=t("profile_tiktok", "en"),
        status=t(f"readiness_{report.status}", "en"),
        score=report.score,
    )
    assert expected in [label.text() for label in popover.findChildren(QLabel)]


def test_settings_dialog_remediation_switches_roundtrip(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    settings = Settings(reduce_motion=True)
    dialog = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(dialog)

    assert not dialog._fix_vfr.isChecked()
    assert not dialog._fix_codec.isChecked()
    assert not dialog._cap_resolution.isChecked()

    dialog._fix_vfr.setChecked(True)
    dialog._fix_codec.setChecked(True)
    dialog._cap_resolution.setChecked(True)
    dialog._apply()

    assert settings.auto_fix_vfr is True
    assert settings.auto_fix_codec is True
    assert settings.auto_cap_resolution is True
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["auto_fix_vfr"] is True
    assert saved["auto_fix_codec"] is True
    assert saved["auto_cap_resolution"] is True

    reopened = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(reopened)
    assert reopened._fix_vfr.isChecked()
    assert reopened._fix_codec.isChecked()
    assert reopened._cap_resolution.isChecked()
