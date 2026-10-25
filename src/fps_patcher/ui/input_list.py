"""Input list widget displaying items in InputQueue with modern cards, badges, and controls."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tkinter import Menu, filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ..app.controller import AppController
from ..app.queue_model import QueueItem
from ..core.models import SUPPORTED_EXTENSIONS, LogEvent, LogLevel
from ..core.platform_profiles import ReadinessReport, evaluate_readiness, get_profile
from .drop_zone import DropZone
from .icons import get_icon
from .strings import t
from .theme import (
    MAC_CHECKBOX_BORDER_WIDTH,
    MAC_CHECKBOX_HEIGHT,
    MAC_CHECKBOX_RADIUS,
    MAC_CHECKBOX_WIDTH,
    MAC_SWITCH_HEIGHT,
    MAC_SWITCH_PROGRESS_COLOR,
    MAC_SWITCH_RADIUS,
    MAC_SWITCH_THUMB_COLOR,
    MAC_SWITCH_TRACK_COLOR,
    MAC_SWITCH_WIDTH,
    RADIUS_PILL,
    STATUS_DANGER_BG,
    STATUS_DANGER_TEXT,
    STATUS_MUTED_BG,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_TEXT,
    ThemeTokens,
    attach_focus_ring,
    configure_cached,
    font_body,
    font_caption,
    get_corner_radii,
    get_theme_manager,
)
from .thumbnails import request_thumbnail

THUMB_SIZE = (72, 44)

# macOS Queue Card Selection Tokens
MAC_ACCENT_BLUE = ("#007AFF", "#0A84FF")
MAC_UNFOCUSED_GREY = ("#D1D1D6", "#3A3A3C")
MAC_UNFOCUSED_BORDER = ("#C7C7CC", "#48484A")
TEXT_WHITE: tuple[str, str] = ("#FFFFFF", "#FFFFFF")
TEXT_SOFT_WHITE: tuple[str, str] = ("#E5F1FF", "#D0E4FF")


def _format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    total_sec = int(round(seconds))
    mins, secs = divmod(total_sec, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _format_meta(item: QueueItem) -> str:
    info = item.info
    if info is None:
        return "—"
    parts: list[str] = []
    if info.width and info.height:
        parts.append(f"{info.width}×{info.height}")
    if info.duration_s:
        parts.append(_format_duration(info.duration_s))
    if info.fps:
        fps_str = f"{info.fps:.2f}".rstrip("0").rstrip(".")
        parts.append(f"{fps_str} fps")
    return " · ".join(parts) if parts else "—"


class InputList(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        controller: AppController,
        on_start_patch_selected: Callable[[], None],
    ) -> None:
        self.controller = controller
        self.settings = controller.settings
        self._on_start_patch_selected = on_start_patch_selected
        self._on_focus_change: Callable[[Path | None], None] | None = None
        self._window_focused: bool = True
        self._focused_path: Path | None = None
        self._theme_mgr = get_theme_manager(self.settings)
        tokens = self._theme_mgr.tokens
        card_rad, _ = get_corner_radii(self.settings.radius_style)

        super().__init__(
            master,
            corner_radius=card_rad,
            fg_color=tokens.bg,
            border_width=0,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._row_widgets: dict[str, ctk.CTkFrame] = {}
        self._row_sigs: dict[str, tuple[Any, ...]] = {}
        self._last_order: list[str] = []
        self._ctk_images: dict[str, ctk.CTkImage] = {}
        self._thumb_requested: set[str] = set()
        self._focus_paint_timer: Any = None
        self._painted_focus_id: str | None = None
        self._can_patch = False
        self._busy = False

        self._build_top_toolbar()
        self._build_scrollable_area()
        self._build_preview_strip()
        self._build_bottom_toolbar()

        self._theme_mgr.subscribe(self.apply_theme)

    @property
    def window_focused(self) -> bool:
        return self._window_focused

    @property
    def focused_path(self) -> Path | None:
        return self._focused_path

    def set_window_focused(self, focused: bool) -> None:
        """Update window focus state and re-render active selection row(s) immediately."""
        if getattr(self, "_window_focused", None) == focused:
            return
        self._window_focused = focused
        items = self.controller.items.items
        if not items:
            return
        active_item = self._resolve_active_item(items)
        active_id = active_item.item_id if active_item is not None else None
        tokens = self._theme_mgr.tokens

        for item in items:
            is_focused = item.item_id == active_id
            if is_focused and item.item_id in self._row_widgets:
                row_frame = self._row_widgets[item.item_id]
                self._update_row_content(row_frame, item, tokens, is_focused=is_focused)
                self._row_sigs[item.item_id] = self._make_sig(item, is_focused=is_focused)

    def set_focused_path(self, path: Path | None) -> None:
        self._focused_path = path
        if path is not None:
            item = self.controller.items.get(path)
            if item is not None and item.info is not None:
                self.controller.current = item.info
        if self._on_focus_change is not None:
            self._on_focus_change(path)
        self.render()

    select_card = set_focused_path

    def set_on_focus_change(self, callback: Callable[[Path | None], None]) -> None:
        self._on_focus_change = callback

    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self.settings.language, **kwargs)

    def _fsize(self) -> str:
        return getattr(self.settings, "font_size", "M")

    def _radii(self) -> tuple[int, int]:
        return get_corner_radii(getattr(self.settings, "radius_style", "Normal"))

    # ---------- top toolbar ----------
    def _build_top_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.top_bar = ctk.CTkFrame(self, fg_color=tokens.bg, height=36)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 6))
        self.top_bar.grid_columnconfigure(2, weight=1)

        # Left buttons: Add Files, Add Folder (soft tinted per Apple HIG spec)
        left_box = ctk.CTkFrame(self.top_bar, fg_color=tokens.bg)
        left_box.grid(row=0, column=0, sticky="w")

        self.btn_add_files = ctk.CTkButton(
            left_box,
            text=f"＋ {self._tr('add_files_btn')}",
            height=28,
            width=96,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._browse_files,
        )
        self.btn_add_files.pack(side="left", padx=(0, 6))

        folder_ico = get_icon("folder", (14, 14))
        self.btn_add_folder = ctk.CTkButton(
            left_box,
            text=self._tr("add_folder_btn") if folder_ico else f"📁 {self._tr('add_folder_btn')}",
            image=folder_ico,
            compound="left",
            height=28,
            width=102,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._browse_folder,
        )
        self.btn_add_folder.pack(side="left", padx=(0, 6))

        # Hidden/compatibility title label
        self.lbl_title = ctk.CTkLabel(
            self.top_bar,
            text="",
            width=1,
            font=font_caption(fsize),
            text_color=tokens.text2,
        )

        # Right buttons: Retry Failed (when needed), Select All, Clear Selection
        right_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_box.grid(row=0, column=3, sticky="e")

        self.btn_retry_failed = ctk.CTkButton(
            right_box,
            text=self._tr("retry_failed"),
            height=28,
            width=92,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=STATUS_WARNING_BG,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=STATUS_WARNING_TEXT,
            command=self._retry_failed,
        )

        self.btn_select_all = ctk.CTkButton(
            right_box,
            text=self._tr("select_all"),
            height=28,
            width=88,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._toggle_select_all,
        )
        self.btn_select_all.pack(side="left", padx=(0, 6))

        self.btn_clear_selection = ctk.CTkButton(
            right_box,
            text=self._tr("clear_selection"),
            height=28,
            width=104,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._clear_selection,
        )
        self.btn_clear_selection.pack(side="left", padx=(0, 6))

        self.btn_clear_all = ctk.CTkButton(
            right_box,
            text=self._tr("clear_all"),
            height=28,
            width=88,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._clear_all,
        )
        self.btn_clear_all.pack(side="left")

        # Compatibility buttons preserved for external references
        self.btn_del_selected = self.btn_clear_selection
        self.btn_clear_inputs = self.btn_clear_all

    # ---------- scrollable list ----------
    def _build_scrollable_area(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=tokens.bg,
            corner_radius=ctrl_rad,
            border_width=0,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Empty state with existing DropZone preserved
        self.drop_zone = DropZone(self.scroll, on_files=self._on_dropped_files)
        self.drop_zone.pack(fill="both", expand=True, padx=4, pady=12)
        self.empty_label = self.drop_zone.label

    # ---------- preview player strip ----------
    def _build_preview_strip(self) -> None:
        tokens = self._theme_mgr.tokens
        card_rad, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.preview_strip = ctk.CTkFrame(
            self,
            corner_radius=card_rad,
            fg_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
        )
        self.preview_strip.grid_columnconfigure(1, weight=1)

        self.preview_thumb_lbl = ctk.CTkLabel(
            self.preview_strip,
            text="🎬",
            width=88,
            height=50,
            corner_radius=8,
            fg_color=tokens.surface,
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_thumb_lbl.grid(row=0, column=0, padx=(10, 10), pady=8)

        info_col = ctk.CTkFrame(self.preview_strip, fg_color="transparent")
        info_col.grid(row=0, column=1, sticky="ew", pady=8)

        self.preview_name_lbl = ctk.CTkLabel(
            info_col,
            text="—",
            font=font_body(bold=True, size_opt=fsize),
            text_color=tokens.text,
            anchor="w",
        )
        self.preview_name_lbl.pack(anchor="w")

        self.preview_meta_lbl = ctk.CTkLabel(
            info_col,
            text="—",
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="w",
        )
        self.preview_meta_lbl.pack(anchor="w")

        self.preview_play_btn = ctk.CTkButton(
            self.preview_strip,
            text=self._tr("open_in_player"),
            height=28,
            width=76,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            border_width=0,
            command=self._play_active_file,
        )
        self.preview_play_btn.grid(row=0, column=2, padx=(8, 12), pady=8)

    # ---------- bottom toolbar ----------
    def _build_bottom_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.bottom_bar = ctk.CTkFrame(
            self,
            fg_color="transparent",
            height=42,
            corner_radius=0,
        )
        self.bottom_bar.grid(row=3, column=0, sticky="ew", padx=4, pady=(6, 0))
        self.bottom_bar.grid_columnconfigure(1, weight=1)

        self.bottom_divider = ctk.CTkFrame(
            self.bottom_bar,
            height=1,
            fg_color=tokens.border,
            corner_radius=0,
        )
        self.bottom_divider.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        # Left: Preview Player switch
        self.player_switch = ctk.CTkSwitch(
            self.bottom_bar,
            text=self._tr("preview_player"),
            font=font_caption(fsize),
            text_color=tokens.text,
            progress_color=MAC_SWITCH_PROGRESS_COLOR,
            fg_color=MAC_SWITCH_TRACK_COLOR,
            button_color=MAC_SWITCH_THUMB_COLOR,
            button_hover_color=MAC_SWITCH_THUMB_COLOR,
            switch_width=MAC_SWITCH_WIDTH,
            switch_height=MAC_SWITCH_HEIGHT,
            corner_radius=MAC_SWITCH_RADIUS,
            height=MAC_SWITCH_HEIGHT,
            command=self._toggle_player,
        )
        self.player_switch.grid(row=1, column=0, sticky="w", padx=4)

        # Center/Right: "N of M selected"
        self.lbl_selected_count = ctk.CTkLabel(
            self.bottom_bar,
            text=self._tr("selected_count", selected=0, total=0),
            font=font_caption(fsize),
            text_color=tokens.muted,
        )
        self.lbl_selected_count.grid(row=1, column=1, sticky="e", padx=(8, 12))

        # Right: Apply Selected (soft blue button calling Start Patch handler)
        self.btn_apply_selected = ctk.CTkButton(
            self.bottom_bar,
            text=self._tr("apply_selected"),
            height=28,
            width=116,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            border_width=0,
            command=self._on_start_patch_selected,
        )
        self.btn_apply_selected.grid(row=1, column=2, sticky="e", padx=2)
        attach_focus_ring(self.btn_apply_selected)

    # ---------- focus & state helpers ----------
    def set_state(self, *, busy: bool) -> None:
        if getattr(self, "_busy", None) == busy:
            return
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (
            getattr(self, "btn_add_files", None),
            getattr(self, "btn_add_folder", None),
            getattr(self, "btn_retry_failed", None),
            getattr(self, "btn_select_all", None),
            getattr(self, "btn_clear_selection", None),
            getattr(self, "btn_clear_all", None),
            getattr(self, "btn_apply_selected", None),
        ):
            if btn is not None:
                with contextlib.suppress(Exception):
                    if btn.cget("state") != state:
                        btn.configure(state=state)
        for row in self._row_widgets.values():
            btn_rem = getattr(row, "_btn_remove", None)
            if btn_rem is not None:
                with contextlib.suppress(Exception):
                    btn_rem.configure(state=state)

    def _resolve_active_item(self, items: list[QueueItem]) -> QueueItem | None:
        """Resolve active QueueItem from controller/queue_model without duplicate state."""
        if not items:
            return None
        if self._focused_path is not None:
            found = self.controller.items.get(self._focused_path)
            if found is not None:
                return found
        if self.controller.current_patching_path is not None:
            found = self.controller.items.get(self.controller.current_patching_path)
            if found is not None:
                return found
        if self.controller.current is not None:
            for it in items:
                if it.info is self.controller.current:
                    return it
        selected = self.controller.items.selected()
        return selected[0] if selected else items[0]

    def _on_card_clicked(self, path: Path) -> None:
        if self._focused_path == path:
            return
        self._focused_path = path
        item = self.controller.items.get(path)
        if item is not None and item.info is not None:
            self.controller.current = item.info
        if self._on_focus_change is not None:
            self._on_focus_change(path)
        # Coalesce repaints: a fast click burst paints only the final selection.
        if self._focus_paint_timer is not None:
            self.after_cancel(self._focus_paint_timer)
        self._focus_paint_timer = self.after(16, self._paint_focus)

    def _paint_focus(self) -> None:
        self._focus_paint_timer = None
        items = self.controller.items.items
        active = self._resolve_active_item(items)
        active_id = active.item_id if active is not None else None
        if active_id == self._painted_focus_id:
            return
        if self._painted_focus_id is not None:
            prev = next((i for i in items if i.item_id == self._painted_focus_id), None)
            if prev is not None:
                self._update_row_focus(prev, is_focused=False)
        if active is not None:
            self._update_row_focus(active, is_focused=True)
        self._painted_focus_id = active_id
        self._update_preview_strip(active)

    def _update_row_focus(self, item: QueueItem, *, is_focused: bool) -> None:
        row = self._row_widgets.get(item.item_id)
        if row is None:
            return
        tokens = self._theme_mgr.tokens
        _, card_rad = get_corner_radii(self.settings.radius_style)

        if is_focused:
            if self._window_focused:
                card_bg = tokens.accent_light
                card_border = tokens.accent
                primary_text_color = tokens.text
                meta_text_color = tokens.text
                sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.muted
            else:
                card_bg = tokens.surface_raised
                card_border = MAC_UNFOCUSED_BORDER
                primary_text_color = tokens.text
                meta_text_color = tokens.muted
                sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.muted
        else:
            card_bg = tokens.surface
            card_border = tokens.border
            primary_text_color = tokens.text
            meta_text_color = tokens.muted
            sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.muted

        configure_cached(row, corner_radius=card_rad, fg_color=card_bg, border_color=card_border)

        path_w = getattr(row, "_lbl_path", None)
        if path_w:
            configure_cached(path_w, text_color=primary_text_color)
        sub_w = getattr(row, "_lbl_sub", None)
        if sub_w:
            configure_cached(sub_w, text_color=sub_text_color)
        meta_w = getattr(row, "_lbl_meta", None)
        if meta_w:
            configure_cached(meta_w, text_color=meta_text_color)

        self._row_sigs[item.item_id] = self._make_sig(item, is_focused=is_focused)

    def _make_sig(self, item: QueueItem, *, is_focused: bool) -> tuple[Any, ...]:
        return (
            item.selected,
            item.status,
            item.error,
            id(item.info) if item.info is not None else None,
            item.timescale,
            item.strategy,
            is_focused,
            self._window_focused,
            self.settings.language,
            self.settings.platform_profile,
            self.settings.radius_style,
            self.settings.font_size,
        )

    # ---------- render queue ----------
    def render(self) -> None:
        """Synchronize UI rows with controller.items (InputQueue) in O(changed) time."""
        items = self.controller.items.items
        total = len(items)
        selected_items = self.controller.items.selected()
        sel_count = len(selected_items)

        configure_cached(
            self.lbl_selected_count,
            text=self._tr("selected_count", selected=sel_count, total=total),
        )
        all_sel = bool(items and sel_count == total)
        configure_cached(
            self.btn_select_all,
            text=self._tr("deselect_all") if all_sel else self._tr("select_all"),
        )

        has_failed = any(i.status in ("failed", "skipped") for i in items)
        if has_failed:
            if not getattr(self.btn_retry_failed, "winfo_ismapped", lambda: False)():
                self.btn_retry_failed.pack(side="left", padx=(0, 6), before=self.btn_select_all)
        else:
            if getattr(self.btn_retry_failed, "winfo_ismapped", lambda: False)():
                self.btn_retry_failed.pack_forget()

        if not items:
            for w in self._row_widgets.values():
                w.destroy()
            self._row_widgets.clear()
            self._row_sigs.clear()
            self._ctk_images.clear()
            self._thumb_requested.clear()
            self._last_order.clear()
            self._painted_focus_id = None
            self.drop_zone.pack(fill="both", expand=True, padx=4, pady=12)
            self._update_preview_strip(None)
            return

        self.drop_zone.pack_forget()

        current_order = [i.item_id for i in items]
        current_ids = set(current_order)

        # Remove deleted rows
        for i_id in list(self._row_widgets.keys()):
            if i_id not in current_ids:
                self._row_widgets[i_id].destroy()
                del self._row_widgets[i_id]
                self._row_sigs.pop(i_id, None)
                self._ctk_images.pop(i_id, None)
                self._thumb_requested.discard(i_id)

        # If FFmpeg became available after initial render, retry missing thumbnails
        missing_thumbs = len(self._ctk_images) < len(self._thumb_requested)
        if self.controller.ffmpeg is not None and missing_thumbs:
            for i_id in list(self._thumb_requested):
                if i_id not in self._ctk_images:
                    self._thumb_requested.discard(i_id)

        tokens = self._theme_mgr.tokens
        active_item = self._resolve_active_item(items)
        active_id = active_item.item_id if active_item is not None else None
        order_changed = current_order != self._last_order

        # Render or update rows only when row signature changes
        for item in items:
            is_focused = item.item_id == active_id
            sig = self._make_sig(item, is_focused=is_focused)
            is_new = item.item_id not in self._row_widgets
            if is_new:
                row_frame = self._create_row_frame(item, tokens, is_focused=is_focused)
                self._row_widgets[item.item_id] = row_frame
                self._row_sigs[item.item_id] = sig
                row_frame.pack(fill="x", pady=4, padx=4)
            else:
                row_frame = self._row_widgets[item.item_id]
                if self._row_sigs.get(item.item_id) != sig:
                    self._update_row_content(row_frame, item, tokens, is_focused=is_focused)
                    self._row_sigs[item.item_id] = sig
                if order_changed:
                    row_frame.pack_forget()
                    row_frame.pack(fill="x", pady=4, padx=4)

            if item.item_id not in self._thumb_requested and self.controller.ffmpeg is not None:
                self._request_row_thumb(row_frame, item)

        self._last_order = current_order
        self._painted_focus_id = active_id
        self._update_preview_strip(active_item)

    def _create_row_frame(
        self, item: QueueItem, tokens: ThemeTokens, *, is_focused: bool = False
    ) -> ctk.CTkFrame:
        card_rad, _ = self._radii()
        fsize = self._fsize()

        if is_focused:
            if self._window_focused:
                card_bg = MAC_ACCENT_BLUE
                card_border = MAC_ACCENT_BLUE
                primary_text_color = TEXT_WHITE
                meta_text_color = TEXT_SOFT_WHITE
                sub_text_color = ("#FFE2E2", "#FFD1D1") if item.error else TEXT_SOFT_WHITE
                rem_btn_color = TEXT_WHITE
                rem_btn_hover = ("#0062CC", "#0071E3")
                chk_border_color = ("#FFFFFF", "#D0E4FF")
                chk_fg_color = ("#FFFFFF", "#FFFFFF")
                chk_mark_color = ("#007AFF", "#0A84FF")
                chk_hover_color = ("#E5F1FF", "#E5F1FF")
                status_cfg = self._status_style(item.status, is_selected=True, window_focused=True)
            else:
                card_bg = MAC_UNFOCUSED_GREY
                card_border = MAC_UNFOCUSED_BORDER
                primary_text_color = tokens.text
                meta_text_color = tokens.text2
                sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.text2
                rem_btn_color = tokens.text2
                rem_btn_hover = ("#BCBCBF", "#48484A")
                chk_border_color = tokens.border
                chk_fg_color = tokens.accent
                chk_mark_color = ("#FFFFFF", "#FFFFFF")
                chk_hover_color = tokens.accent_hover
                status_cfg = self._status_style(item.status, is_selected=True, window_focused=False)
        else:
            card_bg = tokens.surface
            card_border = tokens.border
            primary_text_color = tokens.text
            meta_text_color = tokens.muted
            sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.muted
            rem_btn_color = tokens.muted
            rem_btn_hover = tokens.surface_hover
            chk_border_color = tokens.border
            chk_fg_color = tokens.accent
            chk_mark_color = ("#FFFFFF", "#FFFFFF")
            chk_hover_color = tokens.accent_hover
            status_cfg = self._status_style(
                item.status, is_selected=False, window_focused=self._window_focused
            )

        row = ctk.CTkFrame(
            self.scroll,
            height=64,
            corner_radius=card_rad,
            fg_color=card_bg,
            border_width=1,
            border_color=card_border,
        )
        row.grid_columnconfigure(2, weight=1)

        # 1. Checkbox
        chk = ctk.CTkCheckBox(
            row,
            text="",
            width=20,
            height=20,
            checkbox_width=MAC_CHECKBOX_WIDTH,
            checkbox_height=MAC_CHECKBOX_HEIGHT,
            corner_radius=MAC_CHECKBOX_RADIUS,
            border_width=MAC_CHECKBOX_BORDER_WIDTH,
            fg_color=chk_fg_color,
            hover_color=chk_hover_color,
            border_color=chk_border_color,
            checkmark_color=chk_mark_color,
            command=lambda p=item.path: self._on_toggle(p),
        )
        chk.grid(row=0, column=0, padx=(12, 8), pady=10)
        if item.selected:
            chk.select()
        else:
            chk.deselect()

        # 2. Thumbnail (72x44 rounded 8px)
        cached_img = self._ctk_images.get(item.item_id)
        if cached_img:
            t_bg = tokens.surface_raised
            t_fg = tokens.muted
        elif is_focused and self._window_focused:
            t_bg = ("#005FB8", "#0066CC")
            t_fg = TEXT_WHITE
        elif is_focused and not self._window_focused:
            t_bg = ("#B8B8BD", "#2C2C2E")
            t_fg = tokens.text2
        else:
            t_bg = tokens.surface_raised
            t_fg = tokens.muted

        thumb_lbl = ctk.CTkLabel(
            row,
            text="" if cached_img else "🎬",
            image=cached_img,
            width=THUMB_SIZE[0],
            height=THUMB_SIZE[1],
            corner_radius=8,
            fg_color=t_bg,
            text_color=t_fg,
            font=font_caption(fsize),
        )
        thumb_lbl.grid(row=0, column=1, padx=(0, 12), pady=10)

        # 3. Filename & Path / Error / Overrides
        center_box = ctk.CTkFrame(row, fg_color="transparent")
        center_box.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=8)

        lbl_path = ctk.CTkLabel(
            center_box,
            text=item.path.name,
            font=font_body(bold=True, size_opt=fsize),
            text_color=primary_text_color,
            fg_color="transparent",
            anchor="w",
        )
        lbl_path.pack(anchor="w", fill="x")

        sub_info, is_err = self._format_sub_line(item)
        lbl_sub = ctk.CTkLabel(
            center_box,
            text=sub_info,
            font=font_caption(fsize),
            text_color=sub_text_color,
            fg_color="transparent",
            anchor="w",
        )
        lbl_sub.pack(anchor="w", fill="x")

        # 4. Metadata ("1920×1080 · 00:42 · 60 fps")
        lbl_meta = ctk.CTkLabel(
            row,
            text=_format_meta(item),
            font=font_caption(fsize),
            text_color=meta_text_color,
            fg_color="transparent",
            anchor="e",
        )
        lbl_meta.grid(row=0, column=3, sticky="e", padx=(0, 10), pady=10)

        # 5. Platform Readiness Badge
        readiness_text, readiness_cfg = self._readiness_display(item)
        readiness_badge = ctk.CTkLabel(
            row,
            text=readiness_text,
            font=font_caption(fsize),
            corner_radius=RADIUS_PILL,
            padx=8,
            height=22,
            cursor="hand2",
            **readiness_cfg,
        )
        readiness_badge.grid(row=0, column=4, sticky="e", padx=(0, 6), pady=10)

        # 6. Status Pill Badge
        status_badge = ctk.CTkLabel(
            row,
            text=self._tr(f"status_{item.status}"),
            font=font_caption(fsize),
            corner_radius=RADIUS_PILL,
            padx=10,
            height=22,
            **status_cfg,
        )
        status_badge.grid(row=0, column=5, sticky="e", padx=(0, 8), pady=10)

        # 7. Row Action / Remove Button (✕)
        btn_remove = ctk.CTkButton(
            row,
            text="✕",
            width=22,
            height=22,
            corner_radius=6,
            font=font_caption(fsize),
            fg_color="transparent",
            hover_color=rem_btn_hover,
            text_color=rem_btn_color,
            border_width=0,
            command=lambda p=item.path: self._remove_item(p),
        )
        btn_remove.grid(row=0, column=6, sticky="e", padx=(0, 12), pady=10)
        if self._busy:
            btn_remove.configure(state="disabled")

        # Compatibility & public attributes
        row._chk = chk
        row.chk = chk
        row._thumb = thumb_lbl
        row.thumb = thumb_lbl
        row._center_box = center_box
        row.center_box = center_box
        row._lbl_path = lbl_path
        row.lbl_path = lbl_path
        row._lbl_name = lbl_path
        row.lbl_name = lbl_path
        row._lbl_sub = lbl_sub
        row.lbl_sub = lbl_sub
        row._lbl_meta = lbl_meta
        row.lbl_meta = lbl_meta
        row._res_badge = lbl_meta
        row.res_badge = lbl_meta
        row._fps_badge = lbl_meta
        row.fps_badge = lbl_meta
        row._readiness_badge = readiness_badge
        row.readiness_badge = readiness_badge
        row._status_badge = status_badge
        row.status_badge = status_badge
        row._btn_remove = btn_remove
        row.btn_remove = btn_remove
        row._is_focused = is_focused
        row.is_focused = is_focused
        row._is_selected = is_focused
        row.is_selected = is_focused

        # Click to focus & lazy right-click context menu
        self._bind_row_events(row, item.path)
        return row

    def _request_row_thumb(self, row: ctk.CTkFrame, item: QueueItem) -> None:
        self._thumb_requested.add(item.item_id)
        ff_exe = self.controller.ffmpeg.ffmpeg if self.controller.ffmpeg else None
        thumb_lbl = getattr(row, "_thumb", None)
        if thumb_lbl is None:
            return

        def _on_thumb(
            img: Any | None, tlbl: ctk.CTkLabel = thumb_lbl, i_id: str = item.item_id
        ) -> None:
            self._on_thumb_ready(tlbl, img, i_id)

        request_thumbnail(item.path, ff_exe, THUMB_SIZE, _on_thumb)

    def _format_sub_line(self, item: QueueItem) -> tuple[str, bool]:
        if item.error:
            return f"Error: {item.error}", True
        sub = str(item.path)
        overrides: list[str] = []
        if item.timescale is not None:
            overrides.append(f"{item.timescale} ts")
        if item.strategy is not None:
            overrides.append(item.strategy)
        if overrides:
            sub = f"{sub}  [Override: {', '.join(overrides)}]"
        return sub, False

    def _update_row_content(
        self,
        row: ctk.CTkFrame,
        item: QueueItem,
        tokens: ThemeTokens,
        *,
        is_focused: bool = False,
    ) -> None:
        card_rad, _ = self._radii()
        fsize = self._fsize()

        if is_focused:
            if self._window_focused:
                card_bg = MAC_ACCENT_BLUE
                card_border = MAC_ACCENT_BLUE
                primary_text_color = TEXT_WHITE
                meta_text_color = TEXT_SOFT_WHITE
                sub_text_color = ("#FFE2E2", "#FFD1D1") if item.error else TEXT_SOFT_WHITE
                rem_btn_color = TEXT_WHITE
                rem_btn_hover = ("#0062CC", "#0071E3")
                chk_border_color = ("#FFFFFF", "#D0E4FF")
                chk_fg_color = ("#FFFFFF", "#FFFFFF")
                chk_mark_color = ("#007AFF", "#0A84FF")
                chk_hover_color = ("#E5F1FF", "#E5F1FF")
                status_cfg = self._status_style(item.status, is_selected=True, window_focused=True)
            else:
                card_bg = MAC_UNFOCUSED_GREY
                card_border = MAC_UNFOCUSED_BORDER
                primary_text_color = tokens.text
                meta_text_color = tokens.text2
                sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.text2
                rem_btn_color = tokens.text2
                rem_btn_hover = ("#BCBCBF", "#48484A")
                chk_border_color = tokens.border
                chk_fg_color = tokens.accent
                chk_mark_color = ("#FFFFFF", "#FFFFFF")
                chk_hover_color = tokens.accent_hover
                status_cfg = self._status_style(item.status, is_selected=True, window_focused=False)
        else:
            card_bg = tokens.surface
            card_border = tokens.border
            primary_text_color = tokens.text
            meta_text_color = tokens.muted
            sub_text_color = STATUS_DANGER_TEXT if item.error else tokens.muted
            rem_btn_color = tokens.muted
            rem_btn_hover = tokens.surface_hover
            chk_border_color = tokens.border
            chk_fg_color = tokens.accent
            chk_mark_color = ("#FFFFFF", "#FFFFFF")
            chk_hover_color = tokens.accent_hover
            status_cfg = self._status_style(
                item.status, is_selected=False, window_focused=self._window_focused
            )

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        eff_card_bg = (
            card_bg[1] if is_dark else card_bg[0]
        ) if isinstance(card_bg, (tuple, list)) else card_bg

        row.configure(
            corner_radius=card_rad,
            fg_color=card_bg,
            border_color=card_border,
        )

        center_b = getattr(row, "_center_box", None)
        if center_b:
            center_b.configure(fg_color="transparent")
            with contextlib.suppress(Exception):
                if hasattr(center_b, "_canvas"):
                    center_b._canvas.configure(bg=eff_card_bg)
                if hasattr(center_b, "_draw"):
                    center_b._draw(no_color_updates=False)

        chk_w = getattr(row, "_chk", None)
        if chk_w:
            chk_w.configure(
                fg_color=chk_fg_color,
                hover_color=chk_hover_color,
                border_color=chk_border_color,
                checkmark_color=chk_mark_color,
            )
            if item.selected:
                chk_w.select()
            else:
                chk_w.deselect()

        cached_img = self._ctk_images.get(item.item_id)
        if cached_img:
            t_bg = tokens.surface_raised
            t_fg = tokens.muted
        elif is_focused and self._window_focused:
            t_bg = ("#005FB8", "#0066CC")
            t_fg = TEXT_WHITE
        elif is_focused and not self._window_focused:
            t_bg = ("#B8B8BD", "#2C2C2E")
            t_fg = tokens.text2
        else:
            t_bg = tokens.surface_raised
            t_fg = tokens.muted

        thumb_w = getattr(row, "_thumb", None)
        if thumb_w:
            thumb_w.configure(fg_color=t_bg, text_color=t_fg)

        path_w = getattr(row, "_lbl_path", None)
        if path_w:
            path_w.configure(
                text=item.path.name,
                text_color=primary_text_color,
                fg_color="transparent",
                font=font_body(bold=True, size_opt=fsize),
            )
            with contextlib.suppress(Exception):
                if hasattr(path_w, "_canvas"):
                    path_w._canvas.configure(bg=eff_card_bg)
                if hasattr(path_w, "_draw"):
                    path_w._draw(no_color_updates=False)

        sub_w = getattr(row, "_lbl_sub", None)
        if sub_w:
            sub_info, _ = self._format_sub_line(item)
            sub_w.configure(
                text=sub_info,
                text_color=sub_text_color,
                fg_color="transparent",
                font=font_caption(fsize),
            )
            with contextlib.suppress(Exception):
                if hasattr(sub_w, "_canvas"):
                    sub_w._canvas.configure(bg=eff_card_bg)
                if hasattr(sub_w, "_draw"):
                    sub_w._draw(no_color_updates=False)

        meta_w = getattr(row, "_lbl_meta", None)
        if meta_w:
            meta_w.configure(
                text=_format_meta(item),
                text_color=meta_text_color,
                fg_color="transparent",
                font=font_caption(fsize),
            )
            with contextlib.suppress(Exception):
                if hasattr(meta_w, "_canvas"):
                    meta_w._canvas.configure(bg=eff_card_bg)
                if hasattr(meta_w, "_draw"):
                    meta_w._draw(no_color_updates=False)

        readiness_w = getattr(row, "_readiness_badge", None)
        if readiness_w:
            readiness_text, readiness_cfg = self._readiness_display(item)
            readiness_w.configure(
                text=readiness_text,
                font=font_caption(fsize),
                **readiness_cfg,
            )

        status_w = getattr(row, "_status_badge", None)
        if status_w:
            status_w.configure(
                text=self._tr(f"status_{item.status}"),
                font=font_caption(fsize),
                **status_cfg,
            )

        rem_w = getattr(row, "_btn_remove", None)
        if rem_w:
            rem_w.configure(
                hover_color=rem_btn_hover,
                text_color=rem_btn_color,
                state="disabled" if self._busy else "normal",
            )

        row._is_focused = is_focused
        row.is_focused = is_focused
        row._is_selected = is_focused
        row.is_selected = is_focused

    def _readiness_display(self, item: QueueItem) -> tuple[str, dict[str, Any]]:
        report = evaluate_readiness(item.info, self.settings.platform_profile)
        profile = get_profile(self.settings.platform_profile)
        lang = self.settings.language
        if report.status == "unknown":
            text = t("readiness_unknown_badge", lang, profile=profile.short_name)
        elif report.status == "ready":
            text = t(
                "readiness_badge_ready",
                lang,
                profile=profile.short_name,
                score=report.score,
            )
        else:
            text = t(
                "readiness_badge",
                lang,
                profile=profile.short_name,
                status=t(f"readiness_{report.status}", lang),
                score=report.score,
            )
        return text, self._readiness_style(report)

    def _readiness_style(self, report: ReadinessReport) -> dict[str, Any]:
        if report.status == "ready":
            return {"fg_color": STATUS_SUCCESS_BG, "text_color": STATUS_SUCCESS_TEXT}
        if report.status == "issues":
            return {"fg_color": STATUS_DANGER_BG, "text_color": STATUS_DANGER_TEXT}
        if report.status == "review":
            return {"fg_color": STATUS_WARNING_BG, "text_color": STATUS_WARNING_TEXT}
        return {"fg_color": STATUS_MUTED_BG, "text_color": STATUS_MUTED_TEXT}

    def _log_readiness(self, path: Path) -> None:
        item = self.controller.items.get(path)
        if item is None:
            return
        report = evaluate_readiness(item.info, self.settings.platform_profile)
        profile = get_profile(self.settings.platform_profile)
        lang = self.settings.language
        status_text = t(f"readiness_{report.status}", lang)
        level: LogLevel = (
            "ERROR"
            if report.status == "issues"
            else "WARN"
            if report.status in ("review", "unknown")
            else "OK"
        )
        self.controller.emit(
            LogEvent(
                t(
                    "readiness_log_title",
                    lang,
                    profile=profile.short_name,
                    score=report.score,
                    status=status_text,
                ),
                level,
            )
        )
        for check in report.checks:
            if check.status == "pass":
                continue
            measured = f" ({check.measured})" if check.measured else ""
            self.controller.emit(
                LogEvent(
                    t(
                        "readiness_log_check",
                        lang,
                        check=check.label,
                        status=t(f"check_status_{check.status}", lang),
                        detail=f"{check.detail}{measured}",
                    ),
                    "WARN" if check.status in ("warning", "error") else "INFO",
                )
            )
            if check.recommendation:
                self.controller.emit(
                    LogEvent(
                        t(
                            "readiness_log_recommend",
                            lang,
                            recommendation=check.recommendation,
                        ),
                        "INFO",
                    )
                )

    def _status_style(
        self,
        status: str,
        *,
        is_selected: bool = False,
        window_focused: bool = True,
    ) -> dict[str, Any]:
        tokens = self._theme_mgr.tokens
        if is_selected and window_focused:
            # Contrast-friendly badges on macOS Accent Blue (#007AFF / #0A84FF)
            if status in ("done", "ready"):
                return {"fg_color": ("#198754", "#1E7E34"), "text_color": "#FFFFFF"}
            if status == "failed":
                return {"fg_color": ("#DC3545", "#BD2130"), "text_color": "#FFFFFF"}
            if status == "patching":
                return {"fg_color": ("#0056B3", "#004085"), "text_color": "#FFFFFF"}
            if status in ("skipped", "probing"):
                return {"fg_color": ("#D39E00", "#B9770E"), "text_color": "#FFFFFF"}
            # pending
            return {"fg_color": ("#0056B3", "#004DB3"), "text_color": "#E5F1FF"}

        if status in ("done", "ready"):
            return {"fg_color": STATUS_SUCCESS_BG, "text_color": STATUS_SUCCESS_TEXT}
        if status == "failed":
            return {"fg_color": STATUS_DANGER_BG, "text_color": STATUS_DANGER_TEXT}
        if status == "patching":
            return {"fg_color": tokens.accent_light, "text_color": tokens.accent}
        if status in ("skipped", "probing"):
            return {"fg_color": STATUS_WARNING_BG, "text_color": STATUS_WARNING_TEXT}
        # pending
        return {"fg_color": STATUS_MUTED_BG, "text_color": STATUS_MUTED_TEXT}

    def _on_thumb_ready(self, label: ctk.CTkLabel, img: Any, item_id: str) -> None:
        if img is None:
            return

        def update_ui() -> None:
            try:
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=THUMB_SIZE)
                self._ctk_images[item_id] = ctk_img
                if label.winfo_exists():
                    label.configure(image=ctk_img, text="")
                if bool(self.player_switch.get()):
                    active = self._resolve_active_item(self.controller.items.items)
                    if active is not None and active.item_id == item_id:
                        self._update_preview_strip(active)
            except Exception:
                pass

        with contextlib.suppress(Exception):
            self.after(0, update_ui)

    def _update_preview_strip(self, active_item: QueueItem | None) -> None:
        if not bool(self.player_switch.get()) or active_item is None:
            self.preview_strip.grid_remove()
            self.preview_name_lbl.configure(text="—")
            self.preview_meta_lbl.configure(text="—")
            self.preview_thumb_lbl.configure(image=None, text="🎬")
            return

        self.preview_strip.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 2))
        self.preview_name_lbl.configure(text=active_item.path.name)
        meta_text = _format_meta(active_item)
        self.preview_meta_lbl.configure(text=self._tr("preview_sub", meta=meta_text))
        img = self._ctk_images.get(active_item.item_id)
        if img is not None:
            self.preview_thumb_lbl.configure(image=img, text="")
        else:
            self.preview_thumb_lbl.configure(image=None, text="🎬")

    def _play_active_file(self) -> None:
        active = self._resolve_active_item(self.controller.items.items)
        if active is None or not active.path.exists():
            return
        if hasattr(os, "startfile"):
            os.startfile(str(active.path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(active.path)])
        else:
            subprocess.Popen(["xdg-open", str(active.path)])

    # ---------- user actions ----------
    def _on_dropped_files(self, paths: list[Path]) -> None:
        if paths:
            self._focused_path = paths[-1]
            self.controller.add_files(paths)
            self.render()
            if self._on_focus_change is not None:
                self._on_focus_change(paths[-1])

    def _on_toggle(self, path: Path) -> None:
        self.controller.items.toggle(path)
        items = self.controller.items.items
        sel_count = len(self.controller.items.selected())
        all_sel = bool(items and sel_count == len(items))
        configure_cached(
            self.btn_select_all,
            text=self._tr("deselect_all") if all_sel else self._tr("select_all"),
        )
        configure_cached(
            self.lbl_selected_count,
            text=self._tr("selected_count", selected=sel_count, total=len(items)),
        )

    def _toggle_select_all(self) -> None:
        if self._busy or self.controller.busy:
            return
        items = self.controller.items.items
        all_sel = bool(items and all(i.selected for i in items))
        self.controller.items.select_all(not all_sel)
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if not all_sel else self._tr("select_all")
        )
        self.render()

    def _clear_selection(self) -> None:
        if self._busy or self.controller.busy:
            return
        self.controller.items.select_all(False)
        self.render()

    def _delete_selected(self) -> None:
        if self._busy or self.controller.busy:
            return
        self.controller.remove_selected()
        self.render()

    def _clear_all(self) -> None:
        if self._busy or self.controller.busy:
            return
        if not self.controller.items:
            return
        if messagebox.askyesno(self._tr("clear_all"), self._tr("clear_confirm")):
            self.controller.clear_queue()
            self._ctk_images.clear()
            self._thumb_requested.clear()
            self._focused_path = None
            if self._on_focus_change is not None:
                self._on_focus_change(None)
            self.render()

    def _clear_inputs(self) -> None:
        self._clear_all()

    def _retry_failed(self) -> None:
        if self._busy or self.controller.busy:
            return
        n = self.controller.items.reset_failed()
        if n > 0:
            self.render()
            self._on_start_patch_selected()

    def _browse_files(self) -> None:
        if self._busy or self.controller.busy:
            return
        files = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.mp4;*.mov;*.m4v"),
                ("MP4 files", "*.mp4"),
                ("MOV files", "*.mov"),
                ("All files", "*.*"),
            ],
        )
        if files:
            paths = [Path(p) for p in files]
            self._focused_path = paths[-1]
            self.controller.add_files(paths)
            self.render()
            if self._on_focus_change is not None:
                self._on_focus_change(paths[-1])

    def _browse_folder(self) -> None:
        if self._busy or self.controller.busy:
            return
        folder = filedialog.askdirectory(title="Select folder with video files")
        if folder:
            paths: list[Path] = []
            f_path = Path(folder)
            for root, _, filenames in os.walk(f_path):
                for name in filenames:
                    ext = Path(name).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        paths.append(Path(root) / name)
            if paths:
                self._focused_path = paths[-1]
                self.controller.add_files(paths)
                self.render()
                if self._on_focus_change is not None:
                    self._on_focus_change(paths[-1])
            else:
                msg = "No supported video files found in selected folder."
                messagebox.showinfo("No Videos", msg)

    def _toggle_player(self) -> None:
        self.player_switch.configure(text=self._tr("preview_player"))
        active = self._resolve_active_item(self.controller.items.items)
        self._update_preview_strip(active)

    # ---------- events & lazy context menu ----------
    def _bind_row_events(self, row: ctk.CTkFrame, path: Path) -> None:
        chk = getattr(row, "_chk", None)
        btn_remove = getattr(row, "_btn_remove", None)

        def on_left_click(_event: Any, p: Path = path) -> None:
            self._on_card_clicked(p)

        def on_right_click(event: Any, p: Path = path) -> None:
            self._popup_context_menu(event, p)

        def bind_tree(w: Any) -> None:
            if chk is not None and w is chk:
                w.bind("<Button-3>", on_right_click)
                return
            if btn_remove is not None and w is btn_remove:
                w.bind("<Button-3>", on_right_click)
                return
            w.bind("<Button-1>", on_left_click)
            w.bind("<Button-3>", on_right_click)
            for child in w.winfo_children():
                bind_tree(child)

        bind_tree(row)

        # Readiness badge keeps its detail action in addition to row focus.
        readiness = getattr(row, "_readiness_badge", None)
        if readiness is not None:
            def on_readiness_click(_event: Any, p: Path = path) -> None:
                self._log_readiness(p)

            def bind_readiness(w: Any) -> None:
                w.bind("<Button-1>", on_readiness_click, add="+")
                for child in w.winfo_children():
                    bind_readiness(child)

            bind_readiness(readiness)

    def _popup_context_menu(self, event: Any, path: Path) -> None:
        from ..core.strategies import UI_PRESETS

        item = self.controller.items.get(path)
        if item is None:
            return

        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=f"60 FPS ({self._tr('set_fps')})",
            command=lambda: self._set_item_override(item.path, timescale=60000),
        )
        menu.add_command(
            label=f"120 FPS ({self._tr('set_fps')})",
            command=lambda: self._set_item_override(item.path, timescale=120000),
        )

        preset_menu = Menu(menu, tearoff=0)
        for p_key, p_strat in UI_PRESETS.items():

            def _make_cmd(key: str) -> Callable[[], None]:
                return lambda: self._set_item_override(item.path, strategy=key)

            preset_menu.add_command(
                label=p_strat.label,
                command=_make_cmd(p_key),
            )
        menu.add_cascade(label=self._tr("set_strategy"), menu=preset_menu)

        menu.add_separator()
        menu.add_command(
            label=f"🔧 {self._tr('repair_for_mobile')}",
            command=lambda: self._repair_item_for_mobile(item.path),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("open_containing_folder"),
            command=lambda: self._open_dir(item.path.parent),
        )
        if item.output is not None and item.output.exists():
            out_parent = item.output.parent
            menu.add_command(
                label=self._tr("open_output_file"),
                command=lambda: self._open_dir(out_parent),
            )
        menu.add_command(
            label=self._tr("copy_path"),
            command=lambda: self._copy_to_clip(str(item.path)),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("move_up"),
            command=lambda: self._move_item(item.path, -1),
        )
        menu.add_command(
            label=self._tr("move_down"),
            command=lambda: self._move_item(item.path, 1),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("delete_selected"),
            command=lambda: self._remove_item(item.path),
        )
        menu.add_command(
            label=self._tr("clear_inputs"),
            command=self._clear_inputs,
        )
        menu.post(event.x_root, event.y_root)

    def _set_item_override(
        self, path: Path, timescale: int | None = None, strategy: str | None = None
    ) -> None:
        item = self.controller.items.get(path)
        eff_ts = timescale if timescale is not None else (item.timescale if item else None)
        eff_st = strategy if strategy is not None else (item.strategy if item else None)
        self.controller.items.set_override(path, timescale=eff_ts, strategy=eff_st)
        self.render()
        if self._on_focus_change is not None:
            self._on_focus_change(path)

    def _repair_item_for_mobile(self, path: Path) -> None:
        self.controller.repair_file_for_mobile(path)

    def _move_item(self, path: Path, delta: int) -> None:
        items = self.controller.items.items
        for idx, i in enumerate(items):
            if i.path.resolve() == path.resolve():
                new_idx = max(0, min(idx + delta, len(items) - 1))
                self.controller.items.move(path, new_idx)
                self.render()
                break

    def _remove_item(self, path: Path) -> None:
        if self._focused_path == path:
            self._focused_path = None
        self.controller.items.remove(path)
        self.render()
        if self._on_focus_change is not None:
            active = self._resolve_active_item(self.controller.items.items)
            self._on_focus_change(active.path if active else None)

    def _open_dir(self, directory: Path) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(directory))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(directory)], check=False)
        else:
            subprocess.run(["xdg-open", str(directory)], check=False)

    def _copy_to_clip(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    # ---------- theme update ----------
    def apply_theme(self, tokens: ThemeTokens) -> None:
        card_rad, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.configure(corner_radius=card_rad, fg_color=tokens.bg)
        self.top_bar.configure(fg_color=tokens.bg)
        self.scroll.configure(fg_color=tokens.bg)
        self.btn_add_files.configure(
            text=f"＋ {self._tr('add_files_btn')}",
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        has_folder_ico = bool(self.btn_add_folder.cget("image"))
        folder_txt = (
            self._tr("add_folder_btn")
            if has_folder_ico
            else f"📁 {self._tr('add_folder_btn')}"
        )
        self.btn_add_folder.configure(
            text=folder_txt,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_retry_failed.configure(
            text=self._tr("retry_failed"),
            fg_color=STATUS_WARNING_BG,
            hover_color=tokens.surface_hover,
            text_color=STATUS_WARNING_TEXT,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_select_all.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_clear_selection.configure(
            text=self._tr("clear_selection"),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_clear_all.configure(
            text=self._tr("clear_all"),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.bottom_divider.configure(fg_color=tokens.border)
        self.player_switch.configure(
            text=self._tr("preview_player"),
            text_color=tokens.text,
            progress_color=tokens.success,
            font=font_caption(fsize),
        )
        self.lbl_selected_count.configure(
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.btn_apply_selected.configure(
            text=self._tr("apply_selected"),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.preview_strip.configure(
            corner_radius=card_rad,
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
        )
        self.preview_thumb_lbl.configure(
            fg_color=tokens.surface,
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_name_lbl.configure(
            text_color=tokens.text,
            font=font_body(bold=True, size_opt=fsize),
        )
        self.preview_meta_lbl.configure(
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_play_btn.configure(
            text=self._tr("open_in_player"),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self._row_sigs.clear()
        self.render()
