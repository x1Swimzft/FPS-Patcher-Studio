"""Qt UI: per-item platform profile override and opt-in filename template."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402

from fps_patcher import config  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.models import PatchDoneEvent, VideoInfo  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import main_window as mw  # noqa: E402
from fps_patcher.ui_qt import queue_view as qv  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


def _queue_video(window: Any, tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    window.controller.items.add([video])
    window.queue_view.refresh()
    window.queue_view._focus_row(0, open_player=False)
    return video


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


def test_inspector_override_emits_profile_and_clear_emits_all_none(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = _queue_video(window, tmp_path)
    inspector = window.inspector
    emitted: list[tuple[object, ...]] = []
    inspector.override_changed.connect(lambda *args: emitted.append(args))

    assert inspector.override_profile_combo.findData(None) == 0
    tiktok_index = inspector.override_profile_combo.findData("tiktok")
    assert tiktok_index > 0
    assert inspector.override_profile_combo.itemText(tiktok_index) == t("profile_tiktok", "en")

    inspector.override_switch.setChecked(True)
    inspector.override_fps_edit.setText("90000")
    inspector.override_preset_combo.setCurrentText("X1T 720p")
    inspector.override_profile_combo.setCurrentIndex(tiktok_index)
    inspector.override_apply_btn.click()

    assert len(emitted[-1]) == 4
    assert emitted[-1] == (video, 90000, "tiktok-ts-remux", "tiktok")
    item = window.controller.items.get(video)
    assert item is not None
    assert item.platform_profile == "tiktok"
    assert t("profile_tiktok", "en") in inspector.override_state.text()

    inspector.override_clear_btn.click()

    assert list(emitted[-1]) == [video, None, None, None]
    assert item.platform_profile is None
    assert inspector.override_state.text() == t("inspector_override_inactive", "en")
    window.close()


def test_queue_readiness_prefers_item_profile_over_global(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = _queue_video(window, tmp_path)
    item = window.controller.items.get(video)
    assert item is not None
    item.info = _info(video)
    window.settings.platform_profile = "youtube"

    report = window.queue_view.readiness(item)
    assert report is not None
    assert report.profile_id == "youtube"

    window.controller.items.set_override(video, platform_profile="tiktok")
    report = window.queue_view.readiness(item)
    assert report is not None
    assert report.profile_id == "tiktok"

    window.controller.items.set_override(video, platform_profile=None)
    report = window.queue_view.readiness(item)
    assert report is not None
    assert report.profile_id == "youtube"
    window.close()


def test_override_handler_passes_profile_with_sentinel_semantics() -> None:
    stub = MagicMock()
    path = Path("clip.mp4")

    mw.MainWindow._on_override_changed(stub, path, 90000, "bxd-mobile", "tiktok")
    stub.controller.items.set_override.assert_called_once_with(
        path, timescale=90000, strategy="bxd-mobile", platform_profile="tiktok"
    )

    stub.controller.items.set_override.reset_mock()
    mw.MainWindow._on_override_changed(stub, path, None, None, None)
    stub.controller.items.set_override.assert_called_once_with(
        path, timescale=None, strategy=None, platform_profile=None
    )


def test_patch_done_records_watch_output(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    output = tmp_path / "clip_tiktok_60fps.mp4"
    stub = MagicMock()
    stub._watch_batch_active = True
    stub._watcher = MagicMock()
    stub.settings = SimpleNamespace(language="en", open_when_done=False)
    event = PatchDoneEvent(
        result=None,
        batch_results=cast(Any, [SimpleNamespace(output=output, experimental=False)]),
        total_files=1,
    )

    mw.MainWindow._on_patch_done(stub, event)

    stub._watcher.record_own_output.assert_called_once_with(output)


def test_settings_template_toggle_round_trips_and_preview(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    settings = Settings(reduce_motion=True)

    dialog = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(dialog)
    strategy_labels = [
        dialog._strategy.itemText(index) for index in range(dialog._strategy.count())
    ]
    assert strategy_labels == ["X1T 1080p", "X1T 1080p Mobile", "X1T 720p"]


def test_update_toggle_enabled_without_ffmpeg_network(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    monkeypatch.delenv("FPS_PATCHER_ALLOW_NETWORK", raising=False)
    settings = Settings(reduce_motion=True)

    dialog = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(dialog)

    assert dialog._check_updates.isEnabled()
    assert dialog._check_updates.isChecked()
    assert not dialog._use_template.isChecked()
    assert not dialog._template.isEnabled()
    assert dialog._template_preview.text() == ""

    template = "{name}_{platform}_{strategy}_{fps}fps"
    dialog._use_template.setChecked(True)
    dialog._template.setText(template)
    assert dialog._template.isEnabled()
    assert "sample_clip_tiktok_zilem-v3_60fps.mp4" in dialog._template_preview.text()
    dialog._apply()

    assert settings.use_filename_template is True
    assert settings.filename_template == template

    reopened = SettingsDialog(settings, ThemeManager(settings))
    qtbot.addWidget(reopened)
    assert reopened._use_template.isChecked()
    assert "sample_clip_tiktok_zilem-v3_60fps.mp4" in reopened._template_preview.text()


def test_context_menu_profile_action_keeps_other_overrides(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = _queue_video(window, tmp_path)
    window.controller.items.set_override(
        video, timescale=90000, strategy="bxd-clean"
    )
    window.queue_view.refresh()
    view = window.queue_view

    class AutoMenu(QMenu):
        def exec(self, *_args: object) -> object:  # type: ignore[override]
            for action in self.actions():
                submenu = action.menu()
                if submenu is None or action.text() != view.tr("set_platform_profile"):
                    continue
                for sub in submenu.actions():  # type: ignore[attr-defined]
                    if sub.text() == t("profile_youtube", "en"):
                        return sub
            return None

    monkeypatch.setattr(qv, "QMenu", AutoMenu)
    monkeypatch.setattr(
        view.list_view, "indexAt", lambda _pos: view.model.index(0, 0)
    )
    view._show_context_menu(QPoint(0, 0))

    item = window.controller.items.get(video)
    assert item is not None
    assert item.platform_profile == "youtube"
    assert item.timescale == 90000
    assert item.strategy == "bxd-clean"
    window.close()
