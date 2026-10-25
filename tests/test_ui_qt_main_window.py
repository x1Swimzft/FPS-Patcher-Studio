"""Qt main window shell: metrics, theme toggle, presets, Thai and settings apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QWidget  # noqa: E402

from fps_patcher.config import THEME_PRESETS  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import main_window as mw  # noqa: E402
from fps_patcher.ui_qt.settings_dialog import SettingsDialog  # noqa: E402


def _queue_video(window: Any, tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    window.controller.items.add([video])
    window.queue_view.refresh()
    window.queue_view._focus_row(0, open_player=False)
    return video


def test_default_window_metrics(qtbot: Any, monkeypatch: Any, tmp_path: Path) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)

    assert (window.width(), window.height()) == (1040, 700)
    assert (window.minimumWidth(), window.minimumHeight()) == (880, 600)

    toolbar = window.findChild(QWidget, "Toolbar")
    assert toolbar is not None
    assert toolbar.height() == 44

    assert window.inspector.width() == 300
    assert window.console.height() == 36

    window.console.set_expanded(True)
    assert window.console.height() == 180
    window.console.set_expanded(False)
    assert window.console.height() == 36

    window.close()


def test_settings_dialog_apply_updates_theme_and_density(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    dialog = SettingsDialog(window.settings, window.theme_manager, window)
    qtbot.addWidget(dialog)
    dialog.applied.connect(window._on_settings_applied)

    dialog._preset.setCurrentText("Graphite")
    dialog._density.set_value(dialog._density_labels[1])
    dialog._apply()

    assert window.settings.theme_preset == "Graphite"
    assert window.settings.layout_density == "Comfortable"
    assert window.theme.tokens.name == "Graphite"
    assert window.theme.density.name == "Comfortable"
    assert window.theme.outer == 6
    window.close()


def test_theme_toggle_changes_mode_and_calls_dwm(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    dwm = MagicMock(return_value=True)
    monkeypatch.setattr(mw, "update_title_bar_theme", dwm)
    original_mode = window.theme.mode

    window._toggle_appearance()

    assert window.theme.mode != original_mode
    assert window.theme.mode == window.settings.appearance
    assert dwm.called
    window.close()


def test_thai_language_constructs(qtbot: Any, monkeypatch: Any, tmp_path: Path) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, language="th")

    assert window.inspector.start_btn.text() == t("start_patch", "th")
    assert window.inspector.cancel_btn.text() == t("cancel_btn", "th")
    assert window.console._title.text() == t("activity_console", "th")
    window.close()


def test_language_switch_retranslates_live(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, language="en")
    window.settings.language = "th"
    window.theme_manager.apply(window.settings)

    assert window.inspector.start_btn.text() == t("start_patch", "th")
    assert window.console._title.text() == t("activity_console", "th")
    assert window.queue_view.add_files_button.text() == t("add_files_btn", "th")
    window.close()


def test_custom_fps_is_not_duplicated_in_output(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(
        qtbot,
        monkeypatch,
        tmp_path,
        last_preset="Custom",
        custom_timescale=90000,
    )
    inspector = window.inspector

    assert inspector.custom_label.text() == t("custom_fps_lbl", "en")
    assert inspector.custom_edit.text() == "90"
    assert inspector.timescale_field.text() == "90000"
    assert inspector.timescale() == 90000

    inspector.custom_edit.setText("120")
    inspector._commit_custom()
    assert inspector.timescale() == 120000
    assert inspector.timescale_field.text() == "120000"
    assert window.settings.custom_timescale == 120000
    window.close()


@pytest.mark.parametrize("preset", THEME_PRESETS)
def test_all_seven_presets_construct(
    qtbot: Any, monkeypatch: Any, tmp_path: Path, preset: str
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path, theme_preset=preset)
    assert window.theme.tokens.name == preset
    window.close()


def test_rich_empty_state_has_actions_badges_and_profile_strip(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    drop = window.queue_view.drop_card

    assert not drop.isHidden()
    assert drop.browse_button.text() == t("add_files_btn", "en")
    assert drop.folder_button.text() == t("add_folder_btn", "en")
    assert [label.text() for label in drop.format_labels.values()] == [
        t("format_mp4", "en"),
        t("format_mov", "en"),
        t("format_m4v", "en"),
    ]
    assert drop.profile_title.text() == t("active_patch_profile", "en")
    summary = drop.profile_summary.fullText()
    assert "60 FPS" in summary
    assert "X1T For Mobile" in summary
    assert t("drop_profile_output_same", "en") in summary
    window.close()


def test_override_card_is_compact_until_a_row_is_selected(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    inspector = window.inspector
    assert not inspector.override_empty.isHidden()
    assert inspector.override_form.isHidden()
    assert inspector.override_empty.text() == t("inspector_override_no_selection", "en")

    _queue_video(window, tmp_path)
    assert inspector.override_empty.isHidden()
    assert not inspector.override_form.isHidden()
    assert not inspector.override_switch.isChecked()
    assert inspector.override_state.text() == t("inspector_override_inactive", "en")
    window.close()


def test_override_card_applies_to_controller_item(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = _queue_video(window, tmp_path)
    inspector = window.inspector

    inspector.override_switch.setChecked(True)
    inspector.override_fps_edit.setText("90000")
    inspector.override_preset_combo.setCurrentText("X1T Clean")
    inspector.override_apply_btn.click()

    item = window.controller.items.get(video)
    assert item is not None
    assert item.timescale == 90000
    assert item.strategy == "bxd-clean"
    assert inspector.override_state.text() == t("inspector_override_active", "en")

    inspector.override_clear_btn.click()
    item = window.controller.items.get(video)
    assert item is not None
    assert item.timescale is None and item.strategy is None
    assert inspector.override_state.text() == t("inspector_override_inactive", "en")
    window.close()


def test_forensic_signal_opens_dialog_with_preselected_path(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    created: list[Any] = []

    class FakeDialog:
        def __init__(self, settings: Any, theme_manager: Any, parent: Any = None) -> None:
            self.original_edit = MagicMock()
            self.executed = False
            created.append(self)

        def exec(self) -> None:
            self.executed = True

    monkeypatch.setattr(mw, "ForensicDialog", FakeDialog)
    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = tmp_path / "forensic.mp4"
    video.write_bytes(b"not a real video")

    window.queue_view.forensic_requested.emit(video)

    assert len(created) == 1
    assert created[0].executed
    created[0].original_edit.setText.assert_called_once_with(str(video))
    window.close()


def test_settings_apply_refreshes_profile_strip(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    window.settings.last_preset = "120 FPS"
    window.settings.strategy = "bxd-clean"
    window.settings.output_dir = str(tmp_path)

    window._on_settings_applied(window.settings)

    summary = window.queue_view.drop_card.profile_summary.fullText()
    assert "120 FPS" in summary
    assert "X1T Clean" in summary
    assert t("drop_profile_output_custom", "en") in summary
    window.close()


def _quicktime_info(path: Path) -> Any:
    from fractions import Fraction

    from fps_patcher.core.models import VideoInfo

    return VideoInfo(
        path=path,
        codec="h264",
        width=1080,
        height=1920,
        avg_fps=Fraction(60),
        r_fps=Fraction(60),
        duration_s=10.0,
        timescale=60000,
        nb_frames=600,
        has_audio=True,
        stream_count=2,
        audio_codec="aac",
        bit_rate=8_000_000,
        audio_sample_rate=48_000,
        audio_channels=2,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        color_primaries="bt709",
        color_transfer="bt709",
        color_space="bt709",
        pix_fmt="yuv420p",
        file_size_bytes=path.stat().st_size,
    )


def test_readiness_badge_has_tooltip_and_click_logs_checks(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    window.controller.items.add([video])
    item = window.controller.items.get(video)
    assert item is not None
    item.info = _quicktime_info(video)
    window.queue_view.refresh()
    window.queue_view._focus_row(0, open_player=False)
    window.resize(1600, 900)
    window.show()
    qtbot.waitExposed(window)
    qtbot.wait(1)
    window.queue_view.list_view.viewport().repaint()

    delegate = window.queue_view.delegate
    badge = delegate.readiness_rect(item)
    assert badge is not None

    tooltip = delegate.readiness_tooltip(item)
    assert len(tooltip.splitlines()) > 1
    assert t("readiness_tip", "en") in tooltip

    assert window.queue_view._handle_click(badge.center().toPoint())
    lines = "\n".join(window.console.get_lines())
    assert "[READINESS]" in lines
    assert "100/100" in lines
    assert "Container:" in lines
    window.close()
