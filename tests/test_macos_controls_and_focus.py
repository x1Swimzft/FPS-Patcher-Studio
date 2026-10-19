"""Tests for macOS Controls (MacSwitch, MacCheckBox, MacOptionMenu) and Focus Rings."""

from __future__ import annotations

import contextlib
from collections.abc import Generator

import customtkinter as ctk
import pytest

from fps_patcher.config import Settings
from fps_patcher.ui.control_panel import ControlPanel
from fps_patcher.ui.log_console import LogConsole
from fps_patcher.ui.option_menu import MacOptionMenu
from fps_patcher.ui.settings_tabs.appearance import AppearanceTab
from fps_patcher.ui.settings_tabs.behavior import BehaviorTab
from fps_patcher.ui.settings_tabs.console import ConsoleTab
from fps_patcher.ui.settings_tabs.ffmpeg import FFmpegTab
from fps_patcher.ui.settings_tabs.output import OutputTab
from fps_patcher.ui.settings_tabs.patching import PatchingTab
from fps_patcher.ui.theme import (
    DISABLED_BORDER,
    DISABLED_SURFACE,
    DISABLED_TEXT,
    FOCUS_RING_COLOR,
    MAC_CHECKBOX_BORDER_COLOR,
    MAC_CHECKBOX_BORDER_WIDTH,
    MAC_CHECKBOX_CHECKMARK_COLOR,
    MAC_CHECKBOX_FG_COLOR,
    MAC_CHECKBOX_HEIGHT,
    MAC_CHECKBOX_RADIUS,
    MAC_CHECKBOX_WIDTH,
    MAC_DROPDOWN_RADIUS,
    MAC_SWITCH_HEIGHT,
    MAC_SWITCH_PROGRESS_COLOR,
    MAC_SWITCH_RADIUS,
    MAC_SWITCH_THUMB_COLOR,
    MAC_SWITCH_TRACK_COLOR,
    MAC_SWITCH_WIDTH,
    MacCheckBox,
    MacSwitch,
    attach_focus_ring,
    get_theme_manager,
    style_mac_checkbox,
    style_mac_switch,
)


@pytest.fixture(scope="module")
def tk_root() -> Generator[ctk.CTk, None, None]:
    root = ctk.CTk()
    root.geometry("800x600")
    yield root
    with contextlib.suppress(Exception):
        root.destroy()


# ============================================================================
# 1. FOCUS RING HELPER TESTS
# ============================================================================


def test_attach_focus_ring_on_entry(tk_root: ctk.CTk) -> None:
    entry = ctk.CTkEntry(tk_root, border_width=1, border_color="#D2D2D7")
    entry.pack()
    attach_focus_ring(entry)

    assert entry.cget("border_color") == "#D2D2D7"
    assert entry.cget("border_width") == 1

    # Simulate focus in
    entry._on_focus_in()
    assert entry.cget("border_color") == FOCUS_RING_COLOR
    assert entry.cget("border_width") == 2
    assert entry._is_focus_ring_active is True

    # Simulate focus out
    entry._on_focus_out()
    assert entry.cget("border_color") == "#D2D2D7"
    assert entry.cget("border_width") == 1
    assert entry._is_focus_ring_active is False
    entry.destroy()


def test_attach_focus_ring_on_button(tk_root: ctk.CTk) -> None:
    btn = ctk.CTkButton(tk_root, text="Action", border_width=0, border_color="#D2D2D7")
    btn.pack()
    attach_focus_ring(btn, border_width=2)

    assert btn.cget("border_width") == 0

    # Focus in
    btn._on_focus_in()
    assert btn.cget("border_color") == FOCUS_RING_COLOR
    assert btn.cget("border_width") == 2

    # Focus out
    btn._on_focus_out()
    assert btn.cget("border_color") == "#D2D2D7"
    assert btn.cget("border_width") == 0
    btn.destroy()


def test_attach_focus_ring_disabled_ignored(tk_root: ctk.CTk) -> None:
    entry = ctk.CTkEntry(tk_root, border_width=1, border_color="#D2D2D7", state="disabled")
    entry.pack()
    attach_focus_ring(entry)

    # Focus in should be a no-op when disabled
    entry._on_focus_in()
    assert entry.cget("border_color") == "#D2D2D7"
    assert entry.cget("border_width") == 1
    assert entry._is_focus_ring_active is False
    entry.destroy()


# ============================================================================
# 2. MACOS SWITCH TESTS
# ============================================================================


def test_mac_switch_defaults(tk_root: ctk.CTk) -> None:
    sw = MacSwitch(tk_root, text="Test Switch")
    sw.pack()

    assert sw.cget("switch_width") == MAC_SWITCH_WIDTH
    assert sw.cget("switch_height") == MAC_SWITCH_HEIGHT
    assert sw.cget("corner_radius") == MAC_SWITCH_RADIUS
    assert sw.cget("progress_color") == MAC_SWITCH_PROGRESS_COLOR
    assert sw.cget("fg_color") == MAC_SWITCH_TRACK_COLOR
    assert sw.cget("button_color") == MAC_SWITCH_THUMB_COLOR
    assert sw.cget("button_hover_color") == MAC_SWITCH_THUMB_COLOR
    sw.destroy()


def test_style_mac_switch_helper(tk_root: ctk.CTk) -> None:
    sw = ctk.CTkSwitch(tk_root, text="Raw Switch")
    style_mac_switch(sw)

    assert sw.cget("switch_width") == MAC_SWITCH_WIDTH
    assert sw.cget("switch_height") == MAC_SWITCH_HEIGHT
    assert sw.cget("corner_radius") == MAC_SWITCH_RADIUS
    assert sw.cget("progress_color") == MAC_SWITCH_PROGRESS_COLOR
    assert sw.cget("fg_color") == MAC_SWITCH_TRACK_COLOR
    sw.destroy()


def test_log_console_verbose_switch(tk_root: ctk.CTk) -> None:
    console = LogConsole(tk_root)
    console.pack()

    assert console.verbose.cget("switch_width") == MAC_SWITCH_WIDTH
    assert console.verbose.cget("switch_height") == MAC_SWITCH_HEIGHT
    assert console.verbose.cget("corner_radius") == MAC_SWITCH_RADIUS
    assert console.verbose.cget("progress_color") == MAC_SWITCH_PROGRESS_COLOR
    assert console.verbose.cget("fg_color") == MAC_SWITCH_TRACK_COLOR
    assert console.verbose.cget("button_color") == MAC_SWITCH_THUMB_COLOR
    console.destroy()


# ============================================================================
# 3. MACOS CHECKBOX TESTS
# ============================================================================


def test_mac_checkbox_defaults(tk_root: ctk.CTk) -> None:
    cb = MacCheckBox(tk_root, text="Enable Feature")
    cb.pack()

    assert cb.cget("checkbox_width") == MAC_CHECKBOX_WIDTH
    assert cb.cget("checkbox_height") == MAC_CHECKBOX_HEIGHT
    assert cb.cget("corner_radius") == MAC_CHECKBOX_RADIUS
    assert cb.cget("border_width") == MAC_CHECKBOX_BORDER_WIDTH
    assert cb.cget("fg_color") == MAC_CHECKBOX_FG_COLOR
    assert cb.cget("border_color") == MAC_CHECKBOX_BORDER_COLOR
    assert cb.cget("checkmark_color") == MAC_CHECKBOX_CHECKMARK_COLOR
    cb.destroy()


def test_style_mac_checkbox_helper(tk_root: ctk.CTk) -> None:
    cb = ctk.CTkCheckBox(tk_root, text="Plain Check")
    style_mac_checkbox(cb)

    assert cb.cget("checkbox_width") == MAC_CHECKBOX_WIDTH
    assert cb.cget("checkbox_height") == MAC_CHECKBOX_HEIGHT
    assert cb.cget("corner_radius") == MAC_CHECKBOX_RADIUS
    assert cb.cget("fg_color") == MAC_CHECKBOX_FG_COLOR
    cb.destroy()


def test_control_panel_checkboxes_and_sync(tk_root: ctk.CTk) -> None:
    settings = Settings(
        overwrite=False,
        auto_rename=True,
        v4_dry_run=False,
        backup_original=True,
        verify_after=True,
    )
    panel = ControlPanel(
        tk_root,
        settings=settings,
        on_patch=lambda ts, st: None,
        on_cancel=lambda: None,
    )
    panel.pack()

    # Verify all 5 checkboxes exist as public attributes
    assert hasattr(panel, "overwrite_check")
    assert hasattr(panel, "overwrite_cb")
    assert panel.overwrite_cb is panel.overwrite_check
    assert hasattr(panel, "auto_rename_check")
    assert hasattr(panel, "dry_run_cb")
    assert hasattr(panel, "safe_write_cb")
    assert hasattr(panel, "verify_cb")

    # Dimensions
    for cb in [
        panel.overwrite_check,
        panel.auto_rename_check,
        panel.dry_run_cb,
        panel.safe_write_cb,
        panel.verify_cb,
    ]:
        assert cb.cget("checkbox_width") == MAC_CHECKBOX_WIDTH
        assert cb.cget("checkbox_height") == MAC_CHECKBOX_HEIGHT
        assert cb.cget("corner_radius") == MAC_CHECKBOX_RADIUS

    # Initial states
    assert bool(panel.overwrite_check.get()) is False
    assert bool(panel.auto_rename_check.get()) is True
    assert bool(panel.dry_run_cb.get()) is False
    assert bool(panel.safe_write_cb.get()) is True
    assert bool(panel.verify_cb.get()) is True

    # Toggle dry run and overwrite
    panel.dry_run_cb.select()
    panel.overwrite_cb.select()
    panel._options_changed()

    assert settings.v4_dry_run is True
    assert settings.overwrite is True

    # Re-apply theme
    mgr = get_theme_manager()
    panel.apply_theme(mgr.tokens)
    assert panel.dry_run_cb.cget("fg_color") == MAC_CHECKBOX_FG_COLOR
    assert panel.overwrite_check.cget("fg_color") == MAC_CHECKBOX_FG_COLOR

    panel.destroy()


# ============================================================================
# 4. MACOS OPTION MENU TESTS
# ============================================================================


def test_mac_option_menu_defaults_and_drawing(tk_root: ctk.CTk) -> None:
    menu = MacOptionMenu(tk_root, values=["Alpha", "Beta", "Gamma"])
    menu.pack()
    tk_root.update()

    assert menu.cget("corner_radius") == MAC_DROPDOWN_RADIUS
    assert menu.cget("border_width") == 1
    assert menu.cget("indicator_mode") == "dual"

    # Verify dual chevron vector lines rendered on canvas
    canvas_items = menu._canvas.find_withtag("mac_dual_arrow")
    assert len(canvas_items) == 2

    # Configure border_width and border_color
    menu.configure(border_width=2, border_color="#007AFF")
    assert menu.cget("border_width") == 2
    assert menu.cget("border_color") == "#007AFF"

    # Hover enter and leave cycle
    menu._on_enter()
    menu._on_leave()

    # Single indicator mode
    menu.configure(indicator_mode="single")
    tk_root.update()
    single_items = menu._canvas.find_withtag("mac_dual_arrow")
    assert len(single_items) == 1

    menu.destroy()


def test_control_panel_strategy_menu(tk_root: ctk.CTk) -> None:
    settings = Settings()
    panel = ControlPanel(
        tk_root,
        settings=settings,
        on_patch=lambda ts, st: None,
        on_cancel=lambda: None,
    )
    panel.pack()

    assert isinstance(panel.strategy, MacOptionMenu)
    assert panel.strategy_menu is panel.strategy
    assert panel.strategy.cget("border_width") == 1
    assert panel.strategy.cget("corner_radius") == 8

    panel.destroy()


# ============================================================================
# 5. SETTINGS TABS CONTROLS & FOCUS RINGS
# ============================================================================


class DummySettingsDialog:
    def __init__(self) -> None:
        self._draft = Settings()
        self._theme_mgr = get_theme_manager(self._draft)

    def _tr(self, key: str, **kwargs: object) -> str:
        return key


def test_settings_tabs_switches_and_dropdowns(tk_root: ctk.CTk) -> None:
    dialog = DummySettingsDialog()
    container = ctk.CTkFrame(tk_root)
    container.pack()

    # AppearanceTab
    app_tab = AppearanceTab(container, dialog)
    assert isinstance(app_tab.preset_menu, MacOptionMenu)
    assert app_tab.appearance_menu is app_tab.preset_menu
    assert isinstance(app_tab.glass_mode_menu, MacOptionMenu)
    assert app_tab.backdrop_menu is app_tab.glass_mode_menu
    assert isinstance(app_tab.glass_switch, MacSwitch)
    assert isinstance(app_tab.motion_switch, MacSwitch)
    assert getattr(app_tab.accent_entry, "_is_focus_ring_active", None) is not None

    # BehaviorTab
    beh_tab = BehaviorTab(container, dialog)
    assert isinstance(beh_tab.remember_geo_switch, MacSwitch)
    assert isinstance(beh_tab.ontop_switch, MacSwitch)
    assert isinstance(beh_tab.confirm_cancel_switch, MacSwitch)
    assert isinstance(beh_tab.confirm_overwrite_switch, MacSwitch)
    assert isinstance(beh_tab.lang_menu, MacOptionMenu)

    # ConsoleTab
    con_tab = ConsoleTab(container, dialog)
    assert isinstance(con_tab.log_ts_switch, MacSwitch)
    assert isinstance(con_tab.log_scroll_switch, MacSwitch)
    assert isinstance(con_tab.log_file_switch, MacSwitch)
    assert getattr(con_tab.max_log_entry, "_is_focus_ring_active", None) is not None

    # FFmpegTab
    ff_tab = FFmpegTab(container, dialog)
    assert isinstance(ff_tab.check_on_start_switch, MacSwitch)
    assert isinstance(ff_tab.show_ff_out_switch, MacSwitch)
    assert getattr(ff_tab.ff_dir_entry, "_is_focus_ring_active", None) is not None
    assert getattr(ff_tab.extra_ff_entry, "_is_focus_ring_active", None) is not None

    # OutputTab
    out_tab = OutputTab(container, dialog)
    assert isinstance(out_tab.open_done_switch, MacSwitch)
    assert isinstance(out_tab.preserve_mtime_switch, MacSwitch)
    assert getattr(out_tab.out_dir_entry, "_is_focus_ring_active", None) is not None
    assert getattr(out_tab.tpl_entry, "_is_focus_ring_active", None) is not None

    # PatchingTab
    pat_tab = PatchingTab(container, dialog)
    assert isinstance(pat_tab.strategy_menu, MacOptionMenu)
    assert isinstance(pat_tab.mask_paths_switch, MacSwitch)
    assert isinstance(pat_tab.v4_strict_switch, MacSwitch)
    assert isinstance(pat_tab.v4_sync_switch, MacSwitch)
    assert isinstance(pat_tab.v4_report_switch, MacSwitch)
    assert isinstance(pat_tab.verify_switch, MacSwitch)
    assert isinstance(pat_tab.backup_switch, MacSwitch)
    assert isinstance(pat_tab.stop_err_switch, MacSwitch)
    assert getattr(pat_tab.padding_entry, "_is_focus_ring_active", None) is not None
    assert getattr(pat_tab.tail_ms_entry, "_is_focus_ring_active", None) is not None

    container.destroy()


# ============================================================================
# 6. DISABLED CONTRAST TOKENS
# ============================================================================


def test_disabled_contrast_tokens() -> None:
    assert DISABLED_TEXT == ("#AEAEB2", "#8E8E93")
    assert DISABLED_BORDER == ("#E5E5EA", "#38383A")
    assert DISABLED_SURFACE == ("#F2F2F7", "#2C2C2E")
