"""macOS HIG-styled Pop-up OptionMenu with dual chevron indicator and border styling."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from .theme import (
    BORDER_HAIRLINE,
    MAC_DROPDOWN_RADIUS,
    attach_focus_ring,
)


class MacOptionMenu(ctk.CTkOptionMenu):
    """CustomTkinter CTkOptionMenu conforming to macOS Human Interface Guidelines.

    Features:
    - 8px default corner radius (pill/rounded control).
    - 1px border with theme-aware border color.
    - Dual up/down indicator chevrons (macOS pop-up menu style) or clean single chevron.
    - Unified hover highlighting across the entire control surface.
    - Built-in focus ring support.
    """

    def __init__(
        self,
        master: Any = None,
        *,
        border_width: int = 1,
        border_color: tuple[str, str] | str = BORDER_HAIRLINE,
        indicator_mode: str = "dual",
        corner_radius: int = MAC_DROPDOWN_RADIUS,
        attach_ring: bool = True,
        command: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._border_width = border_width
        self._border_color = border_color
        self._indicator_mode = indicator_mode
        self._corner_radius = corner_radius

        kwargs.setdefault("corner_radius", corner_radius)
        if command is not None:
            kwargs["command"] = command

        super().__init__(master, **kwargs)

        if attach_ring:
            attach_focus_ring(self, normal_color=border_color, border_width=2)

    def configure(self, require_redraw: bool = False, **kwargs: Any) -> None:
        if "border_width" in kwargs:
            self._border_width = kwargs.pop("border_width")
            if not getattr(self, "_is_focus_ring_active", False):
                self._focus_normal_border_width = self._border_width
            require_redraw = True
        if "border_color" in kwargs:
            self._border_color = kwargs.pop("border_color")
            if not getattr(self, "_is_focus_ring_active", False):
                self._focus_normal_border_color = self._border_color
            require_redraw = True
        if "indicator_mode" in kwargs:
            self._indicator_mode = kwargs.pop("indicator_mode")
            require_redraw = True

        super().configure(require_redraw=require_redraw, **kwargs)

    def cget(self, attribute_name: str) -> Any:
        if attribute_name == "border_width":
            return self._border_width
        if attribute_name == "border_color":
            return self._border_color
        if attribute_name == "indicator_mode":
            return self._indicator_mode
        return super().cget(attribute_name)

    def _draw(self, no_color_updates: bool = False) -> None:
        super()._draw(no_color_updates)

        bw = self._apply_widget_scaling(self._border_width)
        left_w = self._current_width - self._current_height
        self._draw_engine.draw_rounded_rect_with_border_vertical_split(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            bw,
            self._apply_widget_scaling(left_w),
        )

        border_col = self._apply_appearance_mode(self._border_color)
        self._canvas.itemconfig("border_parts", outline=border_col, fill=border_col)

        # Clear default or previous arrows
        self._canvas.delete("dropdown_arrow")
        self._canvas.delete("mac_dual_arrow")

        # Draw vector chevrons
        cx = self._apply_widget_scaling(self._current_width - (self._current_height / 2))
        cy = self._apply_widget_scaling(self._current_height / 2)
        arrow_color = self._apply_appearance_mode(self._text_color)
        if self._state == tk.DISABLED:
            arrow_color = self._apply_appearance_mode(self._text_color_disabled)

        line_w = max(1, int(round(self._apply_widget_scaling(1.5))))
        span = self._apply_widget_scaling(3.5)

        if self._indicator_mode == "single":
            self._canvas.create_line(
                cx - span,
                cy - 2,
                cx,
                cy + 3,
                cx + span,
                cy - 2,
                width=line_w,
                fill=arrow_color,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags="mac_dual_arrow",
            )
        else:
            # Dual up/down indicator chevrons (macOS pop-up button HIG)
            self._canvas.create_line(
                cx - span,
                cy - 2,
                cx,
                cy - 5.5,
                cx + span,
                cy - 2,
                width=line_w,
                fill=arrow_color,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags="mac_dual_arrow",
            )
            self._canvas.create_line(
                cx - span,
                cy + 2,
                cx,
                cy + 5.5,
                cx + span,
                cy + 2,
                width=line_w,
                fill=arrow_color,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags="mac_dual_arrow",
            )

    def _on_enter(self, event: Any = 0) -> None:
        super()._on_enter(event)
        if self._hover is True and self._state == tk.NORMAL and len(self._values) > 0:
            hover_col = self._apply_appearance_mode(self._button_hover_color)
            self._canvas.itemconfig("inner_parts_left", outline=hover_col, fill=hover_col)
            self._canvas.itemconfig("inner_parts_right", outline=hover_col, fill=hover_col)
            with contextlib.suppress(Exception):
                self._text_label.configure(bg=hover_col)

    def _on_leave(self, event: Any = 0) -> None:
        super()._on_leave(event)
        fg_col = self._apply_appearance_mode(self._fg_color)
        btn_col = self._apply_appearance_mode(self._button_color)
        self._canvas.itemconfig("inner_parts_left", outline=fg_col, fill=fg_col)
        self._canvas.itemconfig("inner_parts_right", outline=btn_col, fill=btn_col)
        with contextlib.suppress(Exception):
            self._text_label.configure(bg=fg_col)
