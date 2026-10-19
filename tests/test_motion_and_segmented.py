"""Tests for Animation Helper, MacSegmentedControl, and Animated Console Drawer."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Generator

import customtkinter as ctk
import pytest

from fps_patcher.config import Settings
from fps_patcher.ui.animation import (
    animate,
    cancel_animation,
    ease_out_cubic,
    is_animating,
)
from fps_patcher.ui.control_panel import CUSTOM, ControlPanel
from fps_patcher.ui.icons import clear_icon_cache
from fps_patcher.ui.log_console import COLLAPSED_HEIGHT, EXPANDED_HEIGHT, LogConsole
from fps_patcher.ui.segmented_control import (
    DEFAULT_ACTIVE_TEXT,
    DEFAULT_INACTIVE_TEXT,
    DEFAULT_THUMB_BORDER,
    DEFAULT_THUMB_COLOR,
    DEFAULT_TRACK_COLOR,
    DISABLED_ACTIVE_TEXT,
    DISABLED_INACTIVE_TEXT,
    DISABLED_THUMB_BORDER,
    DISABLED_THUMB_COLOR,
    MacSegmentedControl,
    _round_rect_points,
)


@pytest.fixture(scope="module")
def tk_root() -> Generator[ctk.CTk, None, None]:
    root = ctk.CTk()
    yield root
    with contextlib.suppress(Exception):
        root.destroy()


@pytest.fixture(autouse=True)
def clean_icons() -> Generator[None, None, None]:
    clear_icon_cache()
    yield
    clear_icon_cache()


# ============================================================================
# 1. ANIMATION HELPER TESTS
# ============================================================================


def test_ease_out_cubic_curve() -> None:
    # f(t) = 1.0 - (1.0 - t)**3
    assert ease_out_cubic(0.0) == 0.0
    assert pytest.approx(ease_out_cubic(0.5), rel=1e-4) == 0.875
    assert ease_out_cubic(1.0) == 1.0
    # Boundary clamps
    assert ease_out_cubic(-0.5) == 0.0
    assert ease_out_cubic(1.5) == 1.0


def test_animate_reduce_motion_snaps_instantly(tk_root: ctk.CTk) -> None:
    steps: list[float] = []
    done_called = False

    def on_step(val: float) -> None:
        steps.append(val)

    def on_done() -> None:
        nonlocal done_called
        done_called = True

    # With reduce_motion=True
    res = animate(
        tk_root,
        start_val=10.0,
        end_val=50.0,
        duration_ms=200,
        on_step=on_step,
        on_done=on_done,
        reduce_motion=True,
    )
    assert res is None
    assert steps == [50.0]
    assert done_called is True

    # With duration_ms <= 0
    steps.clear()
    done_called = False
    animate(
        tk_root,
        start_val=0.0,
        end_val=100.0,
        duration_ms=0,
        on_step=on_step,
        on_done=on_done,
        reduce_motion=False,
    )
    assert steps == [100.0]
    assert done_called is True


def test_animate_already_at_target(tk_root: ctk.CTk) -> None:
    steps: list[float] = []

    animate(
        tk_root,
        start_val=42.0,
        end_val=42.0,
        duration_ms=200,
        on_step=steps.append,
        on_done=lambda: setattr(test_animate_already_at_target, "done", True),
    )
    assert steps == [42.0]
    assert getattr(test_animate_already_at_target, "done", False) is True


def test_animate_cancellation_and_overwrite(tk_root: ctk.CTk) -> None:
    steps1: list[float] = []
    steps2: list[float] = []

    # Start first animation
    job1 = animate(
        tk_root,
        start_val=0.0,
        end_val=100.0,
        duration_ms=500,
        on_step=steps1.append,
        prop_key="test_prop",
    )
    assert job1 is not None
    assert is_animating(tk_root, "test_prop") is True

    # Starting a new animation on same target cancels the first
    job2 = animate(
        tk_root,
        start_val=50.0,
        end_val=200.0,
        duration_ms=500,
        on_step=steps2.append,
        prop_key="test_prop",
    )
    assert job2 is not None

    # Cancel explicitly
    cancel_animation(tk_root, "test_prop")
    assert is_animating(tk_root, "test_prop") is False


def test_animate_completes_over_time(tk_root: ctk.CTk) -> None:
    steps: list[float] = []

    animate(
        tk_root,
        start_val=0.0,
        end_val=10.0,
        duration_ms=50,
        step_interval_ms=10,
        on_step=steps.append,
        on_done=lambda: setattr(test_animate_completes_over_time, "done", True),
    )
    assert len(steps) >= 1
    assert steps[0] == 0.0

    # Pump Tkinter events until finished
    for _ in range(25):
        tk_root.update()
        if getattr(test_animate_completes_over_time, "done", False):
            break
        tk_root.after(15)

    assert getattr(test_animate_completes_over_time, "done", False) is True
    assert steps[-1] == 10.0


# ============================================================================
# 2. MAC SEGMENTED CONTROL TESTS
# ============================================================================


def test_round_rect_points() -> None:
    pts = _round_rect_points(0, 0, 100, 40, 6)
    assert len(pts) > 8
    # Zero or negative radius fallback to rectangle
    rect = _round_rect_points(0, 0, 100, 40, 0)
    assert len(rect) == 8


def test_mac_segmented_control_init_and_get_set(tk_root: ctk.CTk) -> None:
    seg = MacSegmentedControl(tk_root, values=["60 FPS", "120 FPS", "Custom"], width=200, height=34)
    seg.pack()
    tk_root.update()

    # Initial value defaults to first item
    assert seg.get() == "60 FPS"
    assert seg.index() == 0
    assert seg.index("120 FPS") == 1

    # Programmatic set with animation disabled for test
    seg.configure(reduce_motion=True)
    seg.set("120 FPS")
    assert seg.get() == "120 FPS"
    assert seg.index() == 1

    # Setting value not in list
    seg.set("Unknown")
    assert seg.get() == "Unknown"

    seg.destroy()


def test_mac_segmented_control_ctk_compatibility(tk_root: ctk.CTk) -> None:
    cb_values: list[str] = []

    def on_change(val: str) -> None:
        cb_values.append(val)

    seg = MacSegmentedControl(
        tk_root,
        values=["A", "B", "C"],
        command=on_change,
        selected_color="#007AFF",
        selected_hover_color="#0062CC",
        unselected_color="#2E2E33",
        unselected_hover_color="#38383E",
        text_color="#FFFFFF",
        corner_radius=8,
        height=32,
    )
    seg.pack()
    tk_root.update()

    # Verify cget returns compatible properties
    assert seg.cget("values") == ["A", "B", "C"]
    assert seg.cget("selected_color") == "#007AFF"
    assert seg.cget("unselected_color") == "#2E2E33"
    assert seg.cget("text_color") == "#FFFFFF"
    assert seg.cget("state") == "normal"

    # Configure updates
    seg.configure(state="disabled")
    assert seg.cget("state") == "disabled"

    seg.configure(values=["X", "Y"])
    assert seg.get() == "X"
    assert seg.cget("values") == ["X", "Y"]

    # Insert and delete
    seg.insert(1, "Z")
    assert seg.cget("values") == ["X", "Z", "Y"]
    seg.delete(1)
    assert seg.cget("values") == ["X", "Y"]

    seg.destroy()


def test_mac_segmented_control_click_simulation(tk_root: ctk.CTk) -> None:
    selected: list[str] = []

    seg = MacSegmentedControl(
        tk_root,
        values=["60", "120", "Custom"],
        width=300,
        height=34,
        command=selected.append,
        reduce_motion=True,
    )
    seg.pack()
    tk_root.update()

    # Simulate click on middle segment (around x=150)
    event = tk.Event()
    event.x = 150
    event.y = 17
    seg._on_canvas_click(event)

    assert seg.get() == "120"
    assert selected == ["120"]

    # When disabled, click is ignored
    seg.configure(state="disabled")
    event.x = 250
    seg._on_canvas_click(event)
    assert seg.get() == "120"  # unchanged

    seg.destroy()


def test_mac_segmented_control_variable_sync(tk_root: ctk.CTk) -> None:
    var = tk.StringVar(value="Option2")

    seg = MacSegmentedControl(tk_root, values=["Option1", "Option2", "Option3"], variable=var)
    seg.pack()
    tk_root.update()

    # Variable initialized
    assert seg.get() == "Option2"

    # Changing variable updates segmented control
    var.set("Option3")
    assert seg.get() == "Option3"

    # Changing segmented control updates variable
    seg.set("Option1")
    assert var.get() == "Option1"

    seg.destroy()


def test_mac_segmented_control_styling_constants() -> None:
    # Verify macOS HIG color specs
    assert DEFAULT_TRACK_COLOR == ("#E5E5EA", "#1C1C1E")
    assert DEFAULT_THUMB_COLOR == ("#FFFFFF", "#3A3A3C")
    assert DEFAULT_THUMB_BORDER == ("#D1D1D6", "#48484A")
    assert DEFAULT_ACTIVE_TEXT == ("#1D1D1F", "#FFFFFF")
    assert DEFAULT_INACTIVE_TEXT == ("#6E6E73", "#8E8E93")
    assert DISABLED_THUMB_COLOR == ("#EAEAEA", "#2C2C2E")
    assert DISABLED_THUMB_BORDER == ("#D1D1D6", "#3A3A3C")
    assert DISABLED_ACTIVE_TEXT == ("#8E8E93", "#6E6E73")
    assert DISABLED_INACTIVE_TEXT == ("#AEAEB2", "#545458")


# ============================================================================
# 3. CONTROL PANEL INTEGRATION TESTS
# ============================================================================


def test_control_panel_fps_seg_attributes(tk_root: ctk.CTk) -> None:
    settings = Settings()

    cp = ControlPanel(
        tk_root,
        settings=settings,
        on_patch=lambda ts, strat: None,
        on_cancel=lambda: None,
    )
    cp.pack()
    tk_root.update()

    # Ensure self.fps_seg exists and is a MacSegmentedControl
    assert hasattr(cp, "fps_seg")
    assert isinstance(cp.fps_seg, MacSegmentedControl)

    # Ensure self.preset is preserved as an alias
    assert hasattr(cp, "preset")
    assert cp.preset is cp.fps_seg

    # Ensure .get() and .set() work on both attributes
    assert cp.fps_seg.get() in ("60 FPS", "120 FPS", CUSTOM)
    assert cp.preset.get() == cp.fps_seg.get()

    cp.fps_seg.set("120 FPS")
    assert cp.preset.get() == "120 FPS"

    cp.preset.set("60 FPS")
    assert cp.fps_seg.get() == "60 FPS"

    cp.destroy()


# ============================================================================
# 4. ANIMATED CONSOLE DRAWER TESTS
# ============================================================================


def test_log_console_drawer_toggle_and_animation(tk_root: ctk.CTk) -> None:
    console = LogConsole(tk_root)
    console.pack()
    tk_root.update()

    # Initially expanded
    assert console.is_expanded is True
    assert console.cget("height") == EXPANDED_HEIGHT

    # Collapse drawer with reduce_motion=True (instant)
    console._theme_mgr.settings.reduce_motion = True
    console.set_expanded(False)
    assert console.is_expanded is False
    assert console.cget("height") == COLLAPSED_HEIGHT
    assert console.chevron_btn.cget("text") in ("▸", "")

    # Expand drawer
    console.set_expanded(True)
    assert console.is_expanded is True
    assert console.cget("height") == EXPANDED_HEIGHT
    assert console.chevron_btn.cget("text") in ("▾", "")

    # Toggle drawer
    console.toggle_drawer()
    assert console.is_expanded is False
    assert console.cget("height") == COLLAPSED_HEIGHT

    console.destroy()


def test_log_console_drawer_smooth_animation(tk_root: ctk.CTk) -> None:
    console = LogConsole(tk_root)
    console.pack()
    tk_root.update()

    # Enable smooth animation (reduce_motion=False)
    console._theme_mgr.settings.reduce_motion = False
    console.set_expanded(False)

    # Let animation frames process
    for _ in range(30):
        tk_root.update()
        if console.cget("height") == COLLAPSED_HEIGHT:
            break
        tk_root.after(15)

    assert console.cget("height") == COLLAPSED_HEIGHT
    assert console.is_expanded is False

    # Expand with animation
    console.set_expanded(True)
    for _ in range(30):
        tk_root.update()
        if console.cget("height") == EXPANDED_HEIGHT:
            break
        tk_root.after(15)

    assert console.cget("height") == EXPANDED_HEIGHT
    assert console.is_expanded is True

    console.destroy()
