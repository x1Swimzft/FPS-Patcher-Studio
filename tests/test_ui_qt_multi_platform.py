"""Qt settings dialog: multi-platform export checkboxes and draft/apply persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel  # noqa: E402

from fps_patcher import config  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


@pytest.fixture
def appdata(monkeypatch: Any, tmp_path: Path) -> Path:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    return tmp_path


def _dialog(qtbot: Any, settings: Settings) -> SettingsDialog:
    dialog = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(dialog)
    return dialog


def _checked(dialog: SettingsDialog) -> list[str]:
    return [profile_id for profile_id, check in dialog._export_checks.items() if check.isChecked()]


def test_dialog_reflects_saved_export_platforms(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(
        qtbot,
        Settings(export_platforms=["tiktok", "youtube"], reduce_motion=True),
    )

    assert list(dialog._export_checks) == ["tiktok", "instagram", "youtube"]
    assert _checked(dialog) == ["tiktok", "youtube"]
    hints = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog._tr("export_platforms_help") in hints


def test_apply_persists_checked_platforms_in_profile_order(qtbot: Any, appdata: Path) -> None:
    settings = Settings(reduce_motion=True)
    dialog = _dialog(qtbot, settings)

    dialog._export_checks["instagram"].setChecked(True)
    dialog._export_checks["tiktok"].setChecked(True)
    dialog._apply()

    assert settings.export_platforms == ["tiktok", "instagram"]
    assert Settings.load(appdata / "settings.json").export_platforms == [
        "tiktok",
        "instagram",
    ]


def test_unchecking_all_platforms_persists_empty_list(qtbot: Any, appdata: Path) -> None:
    settings = Settings(export_platforms=["tiktok", "instagram"], reduce_motion=True)
    dialog = _dialog(qtbot, settings)

    for check in dialog._export_checks.values():
        check.setChecked(False)
    dialog._apply()

    assert settings.export_platforms == []
    assert Settings.load(appdata / "settings.json").export_platforms == []


def test_legacy_settings_open_with_no_platforms_checked(qtbot: Any, appdata: Path) -> None:
    dialog = _dialog(qtbot, Settings(reduce_motion=True))

    assert dialog._draft.export_platforms == []
    assert _checked(dialog) == []


def test_overwrite_precheck_covers_every_fanned_out_output(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QMessageBox
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    window.settings.overwrite = True
    window.settings.confirm_overwrite = True
    window.settings.export_platforms = ["tiktok", "youtube"]
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    window.controller.items.add([video])
    window.controller.items.select_all(True)
    # Only the second platform's legacy-name output exists.
    (tmp_path / "clip_ts60000_youtube.mp4").write_bytes(b"old output")
    start = MagicMock()
    window.controller.start_patch = start  # type: ignore[method-assign]
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )

    window._start_patch(timescale=60000, strategy="direct-atom")

    assert not start.called
    window.close()
