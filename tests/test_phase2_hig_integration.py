"""Phase 2 HIG Integration Tests.

Validates:
1. MacSegmentedControl values, callbacks, and reduce_motion snap vs animation.
2. Queue row color switching: macOS Accent Blue (focused) vs Unfocused Grey.
3. LogConsole drawer expand/collapse height states.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import customtkinter as ctk
import pytest

from fps_patcher.config import Settings
from fps_patcher.ui.animation import is_animating
from fps_patcher.ui.icons import clear_icon_cache
from fps_patcher.ui.input_list import (
    MAC_ACCENT_BLUE,
    MAC_UNFOCUSED_BORDER,
    MAC_UNFOCUSED_GREY,
    TEXT_SOFT_WHITE,
    TEXT_WHITE,
)
from fps_patcher.ui.log_console import COLLAPSED_HEIGHT, EXPANDED_HEIGHT, LogConsole
from fps_patcher.ui.segmented_control import MacSegmentedControl


@pytest.fixture(autouse=True)
def clean_icons() -> Generator[None, None, None]:
    clear_icon_cache()
    yield
    clear_icon_cache()


@pytest.fixture(scope="module")
def tk_root() -> Generator[ctk.CTk, None, None]:
    clear_icon_cache()
    root = ctk.CTk()
    root.geometry("800x600")
    yield root
    with contextlib.suppress(Exception):
        root.destroy()
    clear_icon_cache()


# ============================================================================
# 1. SEGMENTED CONTROL: VALUES, CALLBACKS, REDUCE_MOTION SNAP VS ANIMATION
# ============================================================================


def test_segmented_control_values_and_callbacks(tk_root: ctk.CTk) -> None:
    callback_calls: list[str] = []

    def on_change(val: str) -> None:
        callback_calls.append(val)

    seg = MacSegmentedControl(
        tk_root,
        values=["60 FPS", "120 FPS", "Custom"],
        command=on_change,
        width=300,
        height=34,
        reduce_motion=True,
    )
    seg.pack()
    tk_root.update()

    # Initial state
    assert seg.get() == "60 FPS"
    assert seg.index() == 0
    assert seg.index("120 FPS") == 1
    assert seg.index("Custom") == 2
    assert callback_calls == []

    # Programmatic set updates value and does NOT trigger callback
    seg.set("120 FPS")
    assert seg.get() == "120 FPS"
    assert seg.index() == 1
    assert callback_calls == []

    # User click on 3rd segment (Custom) triggers callback
    click_event = tk.Event()
    click_event.x = 250  # Right third
    click_event.y = 17
    seg._on_canvas_click(click_event)

    assert seg.get() == "Custom"
    assert seg.index() == 2
    assert callback_calls == ["Custom"]

    # When disabled, click is ignored and callback not fired
    seg.configure(state="disabled")
    click_event.x = 50  # First segment
    seg._on_canvas_click(click_event)
    assert seg.get() == "Custom"
    assert callback_calls == ["Custom"]

    seg.destroy()


def test_segmented_control_reduce_motion_instant_snap_vs_animated(tk_root: ctk.CTk) -> None:
    # A. Instant snap when reduce_motion=True
    seg_snap = MacSegmentedControl(
        tk_root,
        values=["60 FPS", "120 FPS", "Custom"],
        width=300,
        height=34,
        reduce_motion=True,
    )
    seg_snap.pack()
    tk_root.update()

    assert seg_snap._anim_pos == 0.0
    seg_snap.set("Custom")
    # Must immediately snap to index 2.0 with NO active animation
    assert seg_snap._anim_pos == 2.0
    assert not is_animating(seg_snap, "mac_seg_thumb")
    seg_snap.destroy()

    # B. Smooth transition when reduce_motion=False
    seg_anim = MacSegmentedControl(
        tk_root,
        values=["60 FPS", "120 FPS", "Custom"],
        width=300,
        height=34,
        reduce_motion=False,
    )
    seg_anim.pack()
    tk_root.update()

    assert seg_anim._anim_pos == 0.0
    seg_anim.set("Custom")
    # Animation must be actively scheduled/running on mac_seg_thumb
    assert is_animating(seg_anim, "mac_seg_thumb")

    # Pump frames until animation completes
    for _ in range(30):
        tk_root.update()
        if not is_animating(seg_anim, "mac_seg_thumb"):
            break
        tk_root.after(15)

    assert not is_animating(seg_anim, "mac_seg_thumb")
    assert seg_anim._anim_pos == 2.0
    seg_anim.destroy()


# ============================================================================
# 2. QUEUE SELECTION COLOR SWITCHING (ACCENT BLUE VS UNFOCUSED GREY)
# ============================================================================


def test_queue_selection_focused_accent_blue_vs_unfocused_grey(
    tk_root: ctk.CTk, tmp_path: Path
) -> None:
    from fps_patcher.app.controller import AppController
    from fps_patcher.ui.input_list import InputList

    ctrl = AppController(Settings(output_dir=str(tmp_path)))
    f1 = tmp_path / "vid1.mp4"
    f2 = tmp_path / "vid2.mp4"
    f1.write_bytes(b"vid1")
    f2.write_bytes(b"vid2")
    ctrl.add_files([f1, f2])

    from fps_patcher.ui.drop_zone import DropZone

    with patch.object(DropZone, "drop_target_register", return_value=None):
        input_list = InputList(
            tk_root,
            controller=ctrl,
            on_start_patch_selected=lambda: None,
        )
        input_list.pack()
        tk_root.update()

    try:
        it1 = ctrl.items.get(f1)
        it2 = ctrl.items.get(f2)
        assert it1 is not None and it2 is not None

        input_list.set_focused_path(f1)
        input_list.render()
        tk_root.update()

        row1 = input_list._row_widgets[it1.item_id]
        row2 = input_list._row_widgets[it2.item_id]
        tokens = input_list._theme_mgr.tokens

        # 1. Focused window state: row1 should be Accent Blue
        input_list.set_window_focused(True)
        assert input_list.window_focused is True
        assert row1.is_focused is True
        assert row1.cget("fg_color") == MAC_ACCENT_BLUE
        assert row1.cget("border_color") == MAC_ACCENT_BLUE
        assert row1.lbl_name.cget("text_color") == TEXT_WHITE
        assert row1.lbl_meta.cget("text_color") == TEXT_SOFT_WHITE

        # Unselected row2 should have standard surface tokens
        assert row2.is_focused is False
        assert row2.cget("fg_color") == tokens.surface
        assert row2.cget("border_color") == tokens.border

        # 2. Unfocused window state: row1 should switch to Unfocused Grey
        input_list.set_window_focused(False)
        assert input_list.window_focused is False
        assert row1.is_focused is True
        assert row1.cget("fg_color") == MAC_UNFOCUSED_GREY
        assert row1.cget("border_color") == MAC_UNFOCUSED_BORDER
        assert row1.lbl_name.cget("text_color") == tokens.text
        assert row1.lbl_meta.cget("text_color") == tokens.text2

        # Unselected row2 remains surface token
        assert row2.cget("fg_color") == tokens.surface

        # 3. Return focus: row1 switches back to Accent Blue
        input_list.set_window_focused(True)
        assert input_list.window_focused is True
        assert row1.cget("fg_color") == MAC_ACCENT_BLUE
        assert row1.cget("border_color") == MAC_ACCENT_BLUE
        assert row1.lbl_name.cget("text_color") == TEXT_WHITE
        assert row1.lbl_meta.cget("text_color") == TEXT_SOFT_WHITE
    finally:
        input_list.destroy()


# ============================================================================
# 3. CONSOLE DRAWER EXPAND / COLLAPSE HEIGHT STATES
# ============================================================================


def test_console_drawer_height_states_and_motion(tk_root: ctk.CTk) -> None:
    console = LogConsole(tk_root)
    console.pack()
    tk_root.update()

    # Initial state is expanded
    assert console.is_expanded is True
    assert console.cget("height") == EXPANDED_HEIGHT

    # Instant snap collapse when reduce_motion=True
    console._theme_mgr.settings.reduce_motion = True
    console.set_expanded(False)
    assert console.is_expanded is False
    assert console.cget("height") == COLLAPSED_HEIGHT

    # Instant snap expand when reduce_motion=True
    console.set_expanded(True)
    assert console.is_expanded is True
    assert console.cget("height") == EXPANDED_HEIGHT

    # Smooth animation when reduce_motion=False
    console._theme_mgr.settings.reduce_motion = False
    console.set_expanded(False)
    # Pump animation frames
    for _ in range(30):
        tk_root.update()
        if console.cget("height") == COLLAPSED_HEIGHT:
            break
        tk_root.after(15)

    assert console.cget("height") == COLLAPSED_HEIGHT
    assert console.is_expanded is False

    # Smooth expand
    console.set_expanded(True)
    for _ in range(30):
        tk_root.update()
        if console.cget("height") == EXPANDED_HEIGHT:
            break
        tk_root.after(15)

    assert console.cget("height") == EXPANDED_HEIGHT
    assert console.is_expanded is True

    console.destroy()
