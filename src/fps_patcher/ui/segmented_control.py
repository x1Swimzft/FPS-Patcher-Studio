"""macOS-Style Sliding Pill Segmented Control component with smooth ease-out animation."""

from __future__ import annotations

import contextlib
import math
import sys
import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from .animation import animate, cancel_animation, is_animating
from .theme import get_theme_manager

# macOS HIG Segmented Control Color Tokens
DEFAULT_TRACK_COLOR: tuple[str, str] = ("#E5E5EA", "#1C1C1E")
DEFAULT_THUMB_COLOR: tuple[str, str] = ("#FFFFFF", "#3A3A3C")
DEFAULT_THUMB_BORDER: tuple[str, str] = ("#D1D1D6", "#48484A")
DEFAULT_ACTIVE_TEXT: tuple[str, str] = ("#1D1D1F", "#FFFFFF")
DEFAULT_INACTIVE_TEXT: tuple[str, str] = ("#6E6E73", "#8E8E93")

DISABLED_THUMB_COLOR: tuple[str, str] = ("#EAEAEA", "#2C2C2E")
DISABLED_THUMB_BORDER: tuple[str, str] = ("#D1D1D6", "#3A3A3C")
DISABLED_ACTIVE_TEXT: tuple[str, str] = ("#8E8E93", "#6E6E73")
DISABLED_INACTIVE_TEXT: tuple[str, str] = ("#AEAEB2", "#545458")


def _round_rect_points(
    x1: float, y1: float, x2: float, y2: float, r: float, steps: int = 8
) -> list[float]:
    """Calculate polygon coordinate points for a rounded rectangle."""
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if r <= 0.0:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    pts: list[float] = []
    # Top-right arc (-90 deg to 0 deg)
    for i in range(steps + 1):
        th = -math.pi * 0.5 + (math.pi * 0.5 * i / steps)
        pts.extend([x2 - r + math.cos(th) * r, y1 + r + math.sin(th) * r])
    # Bottom-right arc (0 deg to 90 deg)
    for i in range(steps + 1):
        th = 0.0 + (math.pi * 0.5 * i / steps)
        pts.extend([x2 - r + math.cos(th) * r, y2 - r + math.sin(th) * r])
    # Bottom-left arc (90 deg to 180 deg)
    for i in range(steps + 1):
        th = math.pi * 0.5 + (math.pi * 0.5 * i / steps)
        pts.extend([x1 + r + math.cos(th) * r, y2 - r + math.sin(th) * r])
    # Top-left arc (180 deg to 270 deg)
    for i in range(steps + 1):
        th = math.pi + (math.pi * 0.5 * i / steps)
        pts.extend([x1 + r + math.cos(th) * r, y1 + r + math.sin(th) * r])
    return pts


class MacSegmentedControl(ctk.CTkFrame):
    """macOS-style sliding pill segmented control drop-in compatible with CTkSegmentedButton.

    Features
    --------
    - Track background: #E5E5EA (Light) / #1C1C1E (Dark), corner radius 8px.
    - Sliding pill thumb: #FFFFFF (Light) / #3A3A3C (Dark) with 1px border.
    - 200ms cubic ease-out sliding animation on selection change.
    - Instant snap if reduce_motion is enabled.
    - High contrast text: active (#1D1D1F / #FFFFFF), inactive (#6E6E73 / #8E8E93).
    - Full CTkSegmentedButton compatibility (.get(), .set(), .configure(), .cget()).
    """

    def __init__(
        self,
        master: Any,
        width: int = 140,
        height: int = 34,
        corner_radius: int = 8,
        border_width: int = 0,
        fg_color: tuple[str, str] | str = DEFAULT_TRACK_COLOR,
        thumb_color: tuple[str, str] | str = DEFAULT_THUMB_COLOR,
        thumb_border_color: tuple[str, str] | str = DEFAULT_THUMB_BORDER,
        active_text_color: tuple[str, str] | str = DEFAULT_ACTIVE_TEXT,
        inactive_text_color: tuple[str, str] | str = DEFAULT_INACTIVE_TEXT,
        font: tuple[Any, ...] | ctk.CTkFont | None = None,
        values: list[str] | None = None,
        variable: tk.Variable | None = None,
        command: Callable[[str], Any] | None = None,
        state: str = "normal",
        reduce_motion: bool | None = None,
        **kwargs: Any,
    ) -> None:
        # Compatibility aliases for CTkSegmentedButton
        self._sb_selected_color = kwargs.pop("selected_color", None)
        self._sb_selected_hover_color = kwargs.pop("selected_hover_color", None)
        self._sb_unselected_color = kwargs.pop("unselected_color", None)
        self._sb_unselected_hover_color = kwargs.pop("unselected_hover_color", None)
        self._sb_text_color = kwargs.pop("text_color", None)
        self._sb_text_color_disabled = kwargs.pop("text_color_disabled", None)
        self._dynamic_resizing = kwargs.pop("dynamic_resizing", True)

        self._values: list[str] = list(values) if values is not None else ["Segment"]
        self._current_value: str = self._values[0] if self._values else ""
        self._command: Callable[[str], Any] | None = command
        self._state: str = state
        self._font = font
        self._reduce_motion: bool | None = reduce_motion
        self._thumb_corner_radius: int = 6
        self._pad_x: float = 2.0
        self._pad_y: float = 2.0

        self._thumb_color = thumb_color
        self._thumb_border_color = thumb_border_color
        self._active_text_color = active_text_color
        self._inactive_text_color = inactive_text_color

        # Fractional index position of thumb
        has_val = self._current_value in self._values
        init_idx = self._values.index(self._current_value) if has_val else 0
        self._anim_pos: float = float(init_idx)

        # Canvas tags
        self._thumb_tag = f"mac_seg_thumb_{id(self)}"
        self._text_tag_prefix = f"mac_seg_txt_{id(self)}"
        self._text_tags: list[str] = []
        self._painted_active_idx: int = -1

        # Variable synchronization
        self._variable = variable
        self._variable_callback_blocked = False
        self._variable_callback_name: str | None = None

        super().__init__(
            master=master,
            width=width,
            height=height,
            corner_radius=corner_radius,
            border_width=border_width,
            fg_color=fg_color,
            **kwargs,
        )

        if self._variable is not None:
            self._variable_callback_name = self._variable.trace_add("write", self._on_var_changed)
            var_val = str(self._variable.get())  # type: ignore[no-untyped-call]
            if var_val in self._values:
                self.set(var_val, from_variable_callback=True)

        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._update_cursor()

    @property
    def _value_list(self) -> list[str]:
        """Compatibility accessor matching CTkSegmentedButton._value_list."""
        return self._values

    def _is_reduce_motion(self) -> bool:
        if self._reduce_motion is not None:
            return bool(self._reduce_motion)
        try:
            tm = get_theme_manager()
            if tm is not None and hasattr(tm, "settings") and hasattr(tm.settings, "reduce_motion"):
                return bool(tm.settings.reduce_motion)
        except Exception:
            pass
        return False

    def _on_var_changed(self, *_: Any) -> None:
        if not self._variable_callback_blocked and self._variable is not None:
            self.set(str(self._variable.get()), from_variable_callback=True)  # type: ignore[no-untyped-call]

    def _update_cursor(self) -> None:
        if self._state == "disabled":
            self.configure(cursor="arrow")
        else:
            cur = "pointinghand" if sys.platform == "darwin" else "hand2"
            self.configure(cursor=cur)

    def _on_canvas_click(self, event: tk.Event) -> None:
        if self._state == "disabled" or not self._values:
            return
        n = len(self._values)
        total_w = self._apply_widget_scaling(self._current_width)
        pad_x = self._apply_widget_scaling(self._pad_x)
        inner_w = max(1.0, total_w - 2 * pad_x)
        seg_w = inner_w / float(n)

        clicked_idx = int((event.x - pad_x) / seg_w)
        clicked_idx = max(0, min(n - 1, clicked_idx))

        selected_val = self._values[clicked_idx]
        self.set(selected_val, from_button_callback=True)

    def _draw(self, no_color_updates: bool = False) -> None:
        super()._draw(no_color_updates=no_color_updates)
        self._redraw_segments(no_color_updates=no_color_updates)

    def _redraw_segments(self, no_color_updates: bool = False) -> None:
        if not getattr(self, "_values", None) or not getattr(self, "_thumb_tag", None):
            return

        w = self._current_width if self._current_width > 1 else self._desired_width
        h = self._current_height if self._current_height > 1 else self._desired_height
        n = len(self._values)

        pad_x = self._pad_x
        pad_y = self._pad_y
        inner_w = max(1.0, w - 2 * pad_x)
        seg_w = inner_w / float(n)
        thumb_w = seg_w
        thumb_h = max(1.0, h - 2 * pad_y)

        # Current unscaled thumb bounds
        tx1 = pad_x + self._anim_pos * seg_w
        ty1 = pad_y
        tx2 = tx1 + thumb_w
        ty2 = ty1 + thumb_h

        # Scaled bounds
        sx1 = self._apply_widget_scaling(tx1)
        sy1 = self._apply_widget_scaling(ty1)
        sx2 = self._apply_widget_scaling(tx2)
        sy2 = self._apply_widget_scaling(ty2)
        sr = self._apply_widget_scaling(self._thumb_corner_radius)

        thumb_pts = _round_rect_points(sx1, sy1, sx2, sy2, sr)

        # Colors
        is_disabled = self._state == "disabled"
        if is_disabled:
            t_fill = self._apply_appearance_mode(DISABLED_THUMB_COLOR)
            t_border = self._apply_appearance_mode(DISABLED_THUMB_BORDER)
            act_col = self._apply_appearance_mode(DISABLED_ACTIVE_TEXT)
            inact_col = self._apply_appearance_mode(DISABLED_INACTIVE_TEXT)
        else:
            t_fill = self._apply_appearance_mode(self._thumb_color)
            t_border = self._apply_appearance_mode(self._thumb_border_color)
            act_col = self._apply_appearance_mode(self._active_text_color)
            inact_col = self._apply_appearance_mode(self._inactive_text_color)

        # Update or create thumb polygon
        thumb_items = self._canvas.find_withtag(self._thumb_tag)
        if not thumb_items:
            self._canvas.create_polygon(
                thumb_pts,
                fill=t_fill,
                outline=t_border,
                width=1,
                tags=(self._thumb_tag, "mac_seg_part"),
            )
        else:
            self._canvas.coords(self._thumb_tag, *thumb_pts)
            if not no_color_updates:
                self._canvas.itemconfig(self._thumb_tag, fill=t_fill, outline=t_border)

        # Update or create segment text labels
        # Recreate text tags if value list length changed
        if len(self._text_tags) != n:
            for tag in self._text_tags:
                self._canvas.delete(tag)
            self._text_tags = [f"{self._text_tag_prefix}_{i}" for i in range(n)]
            self._painted_active_idx = -1

        target_idx = (
            self._values.index(self._current_value) if self._current_value in self._values else -1
        )

        for i, val in enumerate(self._values):
            tag = self._text_tags[i]
            cx = pad_x + (i + 0.5) * seg_w
            cy = h / 2.0
            scx = self._apply_widget_scaling(cx)
            scy = self._apply_widget_scaling(cy)

            color = act_col if i == target_idx else inact_col

            items = self._canvas.find_withtag(tag)
            if not items:
                self._canvas.create_text(
                    scx,
                    scy,
                    text=val,
                    fill=color,
                    font=self._font,
                    anchor="center",
                    tags=(tag, "mac_seg_part", "mac_seg_text"),
                )
            else:
                self._canvas.coords(tag, scx, scy)
                if not no_color_updates:
                    self._canvas.itemconfig(tag, text=val, fill=color, font=self._font)

        if not no_color_updates:
            self._painted_active_idx = target_idx

        # Ensure correct layer stacking: thumb above background, text above thumb
        self._canvas.tag_raise(self._thumb_tag)
        for tag in self._text_tags:
            self._canvas.tag_raise(tag)

    def _on_anim_step(self, pos: float) -> None:
        self._anim_pos = pos
        self._update_thumb_and_text_coords()

    def _on_anim_done(self) -> None:
        target_idx = (
            self._values.index(self._current_value) if self._current_value in self._values else 0
        )
        self._anim_pos = float(target_idx)
        self._update_thumb_and_text_coords()

    def _update_thumb_and_text_coords(self) -> None:
        if not self._values or not self.winfo_exists():
            return
        w = self._current_width if self._current_width > 1 else self._desired_width
        h = self._current_height if self._current_height > 1 else self._desired_height
        n = len(self._values)

        pad_x = self._pad_x
        pad_y = self._pad_y
        inner_w = max(1.0, w - 2 * pad_x)
        seg_w = inner_w / float(n)
        thumb_w = seg_w
        thumb_h = max(1.0, h - 2 * pad_y)

        tx1 = pad_x + self._anim_pos * seg_w
        ty1 = pad_y
        tx2 = tx1 + thumb_w
        ty2 = ty1 + thumb_h

        sx1 = self._apply_widget_scaling(tx1)
        sy1 = self._apply_widget_scaling(ty1)
        sx2 = self._apply_widget_scaling(tx2)
        sy2 = self._apply_widget_scaling(ty2)
        sr = self._apply_widget_scaling(self._thumb_corner_radius)

        thumb_pts = _round_rect_points(sx1, sy1, sx2, sy2, sr)
        self._canvas.coords(self._thumb_tag, *thumb_pts)
        self._paint_text_colors()

    def _paint_text_colors(self) -> None:
        """Colour labels from the selected segment, so sliding never flickers text."""
        target_idx = (
            self._values.index(self._current_value) if self._current_value in self._values else -1
        )
        if target_idx == self._painted_active_idx:
            return
        self._painted_active_idx = target_idx
        is_disabled = self._state == "disabled"
        act_col = self._apply_appearance_mode(
            DISABLED_ACTIVE_TEXT if is_disabled else self._active_text_color
        )
        inact_col = self._apply_appearance_mode(
            DISABLED_INACTIVE_TEXT if is_disabled else self._inactive_text_color
        )
        for i, tag in enumerate(self._text_tags):
            self._canvas.itemconfig(tag, fill=act_col if i == target_idx else inact_col)

    def set(
        self,
        value: str,
        from_variable_callback: bool = False,
        from_button_callback: bool = False,
    ) -> None:
        """Set the active selected value, sliding the thumb capsule smoothly."""
        if value not in self._values:
            self._current_value = value
            return

        self._current_value = value
        target_idx = self._values.index(value)

        if self._variable is not None and not from_variable_callback:
            self._variable_callback_blocked = True
            try:
                self._variable.set(value)
            finally:
                self._variable_callback_blocked = False

        # Snap when sliding is pointless: reduce motion, hidden control, or a click landing
        # mid-slide. Restarting the 200ms slide on every click is what made spam jitter.
        is_mapped = bool(self.winfo_ismapped()) if hasattr(self, "winfo_ismapped") else True
        if self._is_reduce_motion() or not is_mapped or is_animating(self, "mac_seg_thumb"):
            cancel_animation(self, "mac_seg_thumb")
            self._anim_pos = float(target_idx)
            self._redraw_segments()
        else:
            animate(
                self,
                start_val=self._anim_pos,
                end_val=float(target_idx),
                duration_ms=200,
                on_step=self._on_anim_step,
                on_done=self._on_anim_done,
                reduce_motion=False,
                prop_key="mac_seg_thumb",
            )

        if from_button_callback and self._command is not None:
            self._command(self._current_value)

    def get(self) -> str:
        """Return the currently selected segment value."""
        return self._current_value

    def index(self, value: str | None = None) -> int:
        """Return index of selected value or specified value."""
        v = self._current_value if value is None else value
        return self._values.index(v)

    def insert(self, index: int, value: str) -> None:
        """Insert a segment option at specified index."""
        if value not in self._values and value != "":
            self._values.insert(index, value)
            self._redraw_segments()

    def delete(self, index: int) -> None:
        """Delete segment option at specified index."""
        if 0 <= index < len(self._values):
            self._values.pop(index)
            if self._current_value not in self._values:
                self._current_value = self._values[0] if self._values else ""
            self._redraw_segments()

    def configure(self, **kwargs: Any) -> None:
        """Configure widget attributes compatible with CTkSegmentedButton."""
        redraw_needed = False

        if "values" in kwargs:
            self._values = list(kwargs.pop("values"))
            if self._current_value not in self._values and self._values:
                self._current_value = self._values[0]
            has_val = self._current_value in self._values
            target_idx = self._values.index(self._current_value) if has_val else 0
            self._anim_pos = float(target_idx)
            redraw_needed = True

        if "command" in kwargs:
            self._command = kwargs.pop("command")

        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self._update_cursor()
            redraw_needed = True

        if "font" in kwargs:
            self._font = kwargs.pop("font")
            redraw_needed = True

        if "reduce_motion" in kwargs:
            self._reduce_motion = kwargs.pop("reduce_motion")

        if "thumb_color" in kwargs:
            self._thumb_color = kwargs.pop("thumb_color")
            redraw_needed = True

        if "thumb_border_color" in kwargs:
            self._thumb_border_color = kwargs.pop("thumb_border_color")
            redraw_needed = True

        if "active_text_color" in kwargs:
            self._active_text_color = kwargs.pop("active_text_color")
            redraw_needed = True

        if "inactive_text_color" in kwargs:
            self._inactive_text_color = kwargs.pop("inactive_text_color")
            redraw_needed = True

        # Compatibility kwargs accepted silently
        if "selected_color" in kwargs:
            self._sb_selected_color = kwargs.pop("selected_color")
        if "selected_hover_color" in kwargs:
            self._sb_selected_hover_color = kwargs.pop("selected_hover_color")
        if "unselected_color" in kwargs:
            self._sb_unselected_color = kwargs.pop("unselected_color")
        if "unselected_hover_color" in kwargs:
            self._sb_unselected_hover_color = kwargs.pop("unselected_hover_color")
        if "text_color" in kwargs:
            self._sb_text_color = kwargs.pop("text_color")
        if "text_color_disabled" in kwargs:
            self._sb_text_color_disabled = kwargs.pop("text_color_disabled")

        if kwargs:
            super().configure(**kwargs)
            redraw_needed = True

        if redraw_needed:
            self._redraw_segments()

    def cget(self, attribute_name: str) -> Any:
        """Retrieve widget attribute value compatible with CTkSegmentedButton."""
        if attribute_name == "values":
            return list(self._values)
        if attribute_name == "command":
            return self._command
        if attribute_name == "state":
            return self._state
        if attribute_name == "font":
            return self._font
        if attribute_name == "reduce_motion":
            return self._reduce_motion
        if attribute_name == "selected_color":
            return self._sb_selected_color
        if attribute_name == "selected_hover_color":
            return self._sb_selected_hover_color
        if attribute_name == "unselected_color":
            return self._sb_unselected_color
        if attribute_name == "unselected_hover_color":
            return self._sb_unselected_hover_color
        if attribute_name == "text_color":
            return self._sb_text_color
        if attribute_name == "text_color_disabled":
            return self._sb_text_color_disabled
        if attribute_name == "thumb_color":
            return self._thumb_color
        if attribute_name == "thumb_border_color":
            return self._thumb_border_color
        if attribute_name == "active_text_color":
            return self._active_text_color
        if attribute_name == "inactive_text_color":
            return self._inactive_text_color
        return super().cget(attribute_name)

    def destroy(self) -> None:
        cancel_animation(self, prop_key="mac_seg_thumb")
        if self._variable is not None and self._variable_callback_name is not None:
            with contextlib.suppress(Exception):
                self._variable.trace_remove("write", self._variable_callback_name)
        super().destroy()
