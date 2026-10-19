"""Forensic MP4 Analyzer Window (X1T Compatibility & Semantic Diff UI)."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ..core.bxd_patcher import repair_for_mobile
from ..core.diagnostic_logger import export_diagnostic_log
from ..core.forensic_analyzer import (
    MP4DiffResult,
    compare_mp4_files,
    export_diff_artifacts,
)
from ..core.verifier import verify_mobile_compatibility
from .theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_LIGHT,
    BORDER_HAIRLINE,
    CONSOLE_BG,
    CONSOLE_BORDER,
    RADIUS_CARD,
    RADIUS_CONTROL,
    STATUS_DANGER_TEXT,
    STATUS_EXPERIMENTAL_BG,
    STATUS_EXPERIMENTAL_BORDER,
    STATUS_EXPERIMENTAL_TEXT,
    STATUS_MUTED_BG,
    STATUS_MUTED_BORDER,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_BORDER,
    STATUS_SUCCESS_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_BORDER,
    STATUS_WARNING_TEXT,
    SURFACE_CARD,
    SURFACE_RAISED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WINDOW_BG,
    apply_window_backdrop,
    font_body,
    font_caption,
    font_mono,
    font_section,
)

CHIP_THEMES = {
    "PASS": {
        "bg": STATUS_SUCCESS_BG,
        "border": STATUS_SUCCESS_BORDER,
        "text": STATUS_SUCCESS_TEXT,
    },
    "CHANGED": {
        "bg": ACCENT_LIGHT,
        "border": ACCENT,
        "text": ACCENT_HOVER,
    },
    "WARNING": {
        "bg": STATUS_WARNING_BG,
        "border": STATUS_WARNING_BORDER,
        "text": STATUS_WARNING_TEXT,
    },
    "EXPERIMENTAL": {
        "bg": STATUS_EXPERIMENTAL_BG,
        "border": STATUS_EXPERIMENTAL_BORDER,
        "text": STATUS_EXPERIMENTAL_TEXT,
    },
    "UNKNOWN": {
        "bg": STATUS_MUTED_BG,
        "border": STATUS_MUTED_BORDER,
        "text": STATUS_MUTED_TEXT,
    },
}


class StatusChip(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        title: str,
        initial_status: str = "UNKNOWN",
        initial_label: str = "WAITING",
    ) -> None:
        theme = CHIP_THEMES.get(initial_status, CHIP_THEMES["UNKNOWN"])
        super().__init__(
            master,
            corner_radius=RADIUS_CONTROL,
            border_width=1,
            fg_color=theme["bg"],
            border_color=theme["border"],
        )
        self.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(
            self,
            text=title,
            font=font_caption(),
            text_color=TEXT_MUTED,
        )
        self.title_lbl.grid(row=0, column=0, padx=8, pady=(4, 0), sticky="w")
        self.val_lbl = ctk.CTkLabel(
            self,
            text=initial_label,
            font=font_body(bold=True),
            text_color=theme["text"],
        )
        self.val_lbl.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="w")

    def set_chip(self, status: str, label: str) -> None:
        theme = CHIP_THEMES.get(status, CHIP_THEMES["UNKNOWN"])
        self.configure(fg_color=theme["bg"], border_color=theme["border"])
        self.val_lbl.configure(text=label, text_color=theme["text"])


class ForensicWindow(ctk.CTkToplevel):
    def __init__(self, master: Any) -> None:
        super().__init__(master)
        self.title("MP4 Forensic Analyzer — Container Structure & Atom Diff")
        self.geometry("900x720")
        self.minsize(780, 580)
        self.configure(fg_color=WINDOW_BG)

        # Apply glass backdrop to top-level window as well
        s = getattr(master, "settings", None)
        if s:
            apply_window_backdrop(
                self,
                glass=s.glass,
                alpha=s.window_alpha,
                backdrop_mode=s.glass_mode,
                tint_strength=s.tint_strength,
            )
        else:
            apply_window_backdrop(self, glass=True, alpha=0.96)

        self._diff_result: MP4DiffResult | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_file_picker()
        self._build_summary_card()
        self._build_details_view()
        self._build_footer()

    def _build_file_picker(self) -> None:
        frame = ctk.CTkFrame(
            self,
            corner_radius=RADIUS_CARD,
            fg_color=SURFACE_CARD,
            border_width=1,
            border_color=BORDER_HAIRLINE,
        )
        frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        frame.grid_columnconfigure(1, weight=1)

        # File 1: Original
        ctk.CTkLabel(
            frame,
            text="Original File:",
            font=font_body(bold=True),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=14, pady=8)
        self.orig_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Path to original MP4/MOV...",
            fg_color=SURFACE_RAISED,
            border_color=BORDER_HAIRLINE,
            border_width=1,
            text_color=TEXT_PRIMARY,
            font=font_body(),
        )
        self.orig_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        ctk.CTkButton(
            frame,
            text="Browse…",
            width=80,
            corner_radius=RADIUS_CONTROL,
            command=self._browse_orig,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER_HAIRLINE,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER_HAIRLINE,
            font=font_caption(),
        ).grid(row=0, column=2, padx=(0, 14), pady=8)

        # File 2: X1T / Patched
        ctk.CTkLabel(
            frame,
            text="Target / Patched:",
            font=font_body(bold=True),
            text_color=TEXT_PRIMARY,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=8)
        self.patch_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Path to X1T output or patched file...",
            fg_color=SURFACE_RAISED,
            border_color=BORDER_HAIRLINE,
            border_width=1,
            text_color=TEXT_PRIMARY,
            font=font_body(),
        )
        self.patch_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=8)
        ctk.CTkButton(
            frame,
            text="Browse…",
            width=80,
            corner_radius=RADIUS_CONTROL,
            command=self._browse_patch,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER_HAIRLINE,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER_HAIRLINE,
            font=font_caption(),
        ).grid(row=1, column=2, padx=(0, 14), pady=8)

        # Analyze Button
        self.analyze_btn = ctk.CTkButton(
            frame,
            text="🔬 ANALYZE CONTAINER COMPATIBILITY & ATOMS",
            height=38,
            corner_radius=RADIUS_CONTROL,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._run_analysis,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
        )
        self.analyze_btn.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(6, 14))

    def _build_summary_card(self) -> None:
        self.summary_frame = ctk.CTkFrame(
            self,
            corner_radius=RADIUS_CARD,
            fg_color=SURFACE_CARD,
            border_width=1,
            border_color=BORDER_HAIRLINE,
        )
        self.summary_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        self.summary_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Status Chips
        self.chip_structure = StatusChip(
            self.summary_frame, "Container Structure", "UNKNOWN", "Awaiting input"
        )
        self.chip_structure.grid(row=0, column=0, padx=8, pady=8, sticky="ew")

        self.chip_payload = StatusChip(
            self.summary_frame, "Payload Integrity", "UNKNOWN", "Awaiting input"
        )
        self.chip_payload.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

        self.chip_reencode = StatusChip(
            self.summary_frame, "Re-encode Check", "UNKNOWN", "Awaiting input"
        )
        self.chip_reencode.grid(row=0, column=2, padx=8, pady=8, sticky="ew")

        self.chip_tiktok = StatusChip(
            self.summary_frame, "TikTok 1080p Status", "WARNING", "NOT VERIFIED"
        )
        self.chip_tiktok.grid(row=0, column=3, padx=8, pady=8, sticky="ew")

        # Labels for specific atom/hash match
        hash_row = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        hash_row.grid(row=1, column=0, columnspan=4, sticky="ew", padx=12, pady=(0, 8))
        hash_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.lbl_mdat = ctk.CTkLabel(
            hash_row, text="mdat Hash: —", font=font_caption(), text_color=TEXT_MUTED
        )
        self.lbl_mdat.grid(row=0, column=0, sticky="w", padx=6)

        self.lbl_video = ctk.CTkLabel(
            hash_row, text="Video Payload: —", font=font_caption(), text_color=TEXT_MUTED
        )
        self.lbl_video.grid(row=0, column=1, sticky="w", padx=6)

        self.lbl_audio = ctk.CTkLabel(
            hash_row, text="Audio Payload: —", font=font_caption(), text_color=TEXT_MUTED
        )
        self.lbl_audio.grid(row=0, column=2, sticky="w", padx=6)

    def _build_details_view(self) -> None:
        view_frame = ctk.CTkFrame(
            self,
            corner_radius=RADIUS_CARD,
            fg_color=SURFACE_CARD,
            border_width=1,
            border_color=BORDER_HAIRLINE,
        )
        view_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=6)
        view_frame.grid_columnconfigure(0, weight=1)
        view_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            view_frame,
            text="SCIENTIFIC FORENSIC BREAKDOWN",
            font=font_section(),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        self.details_box = ctk.CTkTextbox(
            view_frame,
            font=font_mono(11),
            fg_color=CONSOLE_BG,
            border_width=1,
            border_color=CONSOLE_BORDER,
            wrap="none",
        )
        self.details_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_footer(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 16))
        bar.grid_columnconfigure(0, weight=1)

        self.repair_btn = ctk.CTkButton(
            bar,
            text="🔧 X1T Repair",
            state="disabled",
            command=self._repair_target,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
        )
        self.repair_btn.grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.save_diag_btn = ctk.CTkButton(
            bar,
            text="Save Diagnostic Log",
            state="disabled",
            command=self._save_diag_log,
            fg_color=SURFACE_CARD,
            hover_color=SURFACE_RAISED,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER_HAIRLINE,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
        )
        self.save_diag_btn.grid(row=0, column=1, padx=6)

        self.export_json_btn = ctk.CTkButton(
            bar,
            text="Export JSON (before/after/diff)",
            state="disabled",
            command=self._export_json,
            fg_color=SURFACE_CARD,
            hover_color=SURFACE_RAISED,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER_HAIRLINE,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
        )
        self.export_json_btn.grid(row=0, column=2, padx=6)

        self.export_report_btn = ctk.CTkButton(
            bar,
            text="Export Forensic Report (Markdown)",
            state="disabled",
            command=self._export_report,
            fg_color=SURFACE_CARD,
            hover_color=SURFACE_RAISED,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER_HAIRLINE,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
        )
        self.export_report_btn.grid(row=0, column=3, padx=(6, 0))

    def _browse_orig(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Original MP4",
            filetypes=[("MP4 / MOV files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
        )
        if path:
            self.orig_entry.delete(0, "end")
            self.orig_entry.insert(0, path)

    def _browse_patch(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Target or Patched MP4",
            filetypes=[("MP4 / MOV files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
        )
        if path:
            self.patch_entry.delete(0, "end")
            self.patch_entry.insert(0, path)

    def _run_analysis(self) -> None:
        p1 = Path(self.orig_entry.get().strip())
        p2 = Path(self.patch_entry.get().strip())
        if not p1.is_file() or not p2.is_file():
            messagebox.showerror(
                "Error", "Please select valid files for both Original and Target."
            )
            return

        try:
            res = compare_mp4_files(p1, p2)
            self._diff_result = res
            mob_rep = verify_mobile_compatibility(p2)
        except Exception as exc:
            messagebox.showerror("Forensic Error", f"Analysis failed: {exc}")
            return

        # Status Chips logic
        is_lossless = res.mdat_match and res.video_payload_match
        if is_lossless:
            self.chip_payload.set_chip("PASS", "Bit-exact Verified")
            self.chip_reencode.set_chip("PASS", "Zero Re-encode")
        else:
            self.chip_payload.set_chip("WARNING", "Payload Diverged")
            self.chip_reencode.set_chip("WARNING", "Possible Re-encode")

        # Container structure analysis
        if not mob_rep.structure_ok:
            self.chip_structure.set_chip("EXPERIMENTAL", "Non-standard (PC only)")
        elif res.structure_match:
            self.chip_structure.set_chip("PASS", "Structure OK (Mobile)")
        else:
            self.chip_structure.set_chip("CHANGED", "Structure OK (Patched)")

        self.chip_tiktok.set_chip("WARNING", "NOT VERIFIED")

        self.lbl_mdat.configure(
            text=f"mdat Hash: {'MATCH ✔' if res.mdat_match else 'CHANGED ❌'}",
            text_color=STATUS_SUCCESS_TEXT if res.mdat_match else STATUS_DANGER_TEXT,
        )
        self.lbl_video.configure(
            text=f"Video Payload: {'MATCH ✔' if res.video_payload_match else 'CHANGED ❌'}",
            text_color=STATUS_SUCCESS_TEXT if res.video_payload_match else STATUS_DANGER_TEXT,
        )
        self.lbl_audio.configure(
            text=f"Audio Payload: {'MATCH ✔' if res.audio_payload_match else 'CHANGED ❌'}",
            text_color=STATUS_SUCCESS_TEXT if res.audio_payload_match else STATUS_DANGER_TEXT,
        )

        if not res.before or not res.after:
            return

        # Update scientific breakdown details
        lines: list[str] = [
            f"Original: {p1.name} ({res.before.file_size:,} bytes)",
            f"Target:   {p2.name} ({res.after.file_size:,} bytes)",
            f"Mobile Compatibility: {mob_rep.status_label}",
            "=" * 70,
            "[0. MOBILE COMPATIBILITY AUDIT]",
            f" • Status:             {mob_rep.status_label}",
            f" • Atom Structure OK:  {mob_rep.atom_structure_ok}",
            f" • Chunk Offsets OK:   {mob_rep.chunk_offsets_ok}",
            f" • Sample Tables OK:   {mob_rep.sample_tables_ok}",
            f" • mvhd Defined:       {mob_rep.mvhd_duration_defined}",
            f" • tkhd Scaling OK:    {mob_rep.tkhd_duration_consistent}",
            f" • Audio A/V Sync OK:  {mob_rep.audio_duration_consistent}",
        ]
        for issue in mob_rep.issues:
            lines.append(f"   ⚠ ISSUE: {issue}")
        for warn in mob_rep.warnings:
            lines.append(f"   ℹ WARN:  {warn}")

        lines.extend(
            [
                "",
                "[1. OBSERVED (Concrete Physical Attributes)]",
                f" • Atom Structure Match: {res.structure_match}",
                f" • Byte Change Spans:   {len(res.byte_diffs)} regions",
                f" • Changed Atoms:       {', '.join(res.changed_atoms) or 'None'}",
                f" • Trailing Ghost Data: {res.after.trailing_data_size} bytes (target file)",
                "",
                "[2. VERIFIED (Empirically Proven by SHA-256)]",
                (
                    " • Video Frame Payload: PASS (Bit-exact)"
                    if res.video_payload_match
                    else " • Video Frame Payload: FAIL (Altered)"
                ),
                (
                    " • Audio Sample Payload: PASS (Bit-exact)"
                    if res.audio_payload_match
                    else " • Audio Sample Payload: FAIL (Altered)"
                ),
                (
                    " • Entire mdat Box: PASS (Bit-exact)"
                    if res.mdat_match
                    else " • Entire mdat Box: FAIL (Altered)"
                ),
                "",
                "[3. NOT VERIFIED (Platform Server Behavior)]",
                " • TikTok 1080p Transcode Bypass: NOT VERIFIED",
                "   (Server transcode rules vary by region, account, and CDN ingestion)",
                "",
                "[4. HYPOTHESIS (Engine Theory)]",
                " • High timescale or indeterminate mvhd may alter server transcode triggers.",
                "",
                "[5. SEMANTIC TIMING DIFFERENCES]",
            ]
        )

        if res.semantic_diffs:
            for s in res.semantic_diffs:
                lines.append(f" • [{s.target}] {s.field}: {s.old_value} -> {s.new_value}")
        else:
            lines.append("   (None)")

        lines.extend(["", "[6. BYTE-LEVEL DIFFERENCES (Preview first 50 spans)]"])
        for b in res.byte_diffs[:50]:
            hint = f" ({b.field_hint})" if b.field_hint else ""
            lines.append(
                f"  offset 0x{b.offset:08x} ({b.length}B) [{b.atom_path}]{hint}: "
                f"{b.old_bytes_hex} -> {b.new_bytes_hex}"
            )
        if len(res.byte_diffs) > 50:
            lines.append(f"  ... and {len(res.byte_diffs) - 50} more spans.")

        self.details_box.delete("1.0", "end")
        self.details_box.insert("1.0", "\n".join(lines))

        self.repair_btn.configure(state="normal")
        self.save_diag_btn.configure(state="normal")
        self.export_json_btn.configure(state="normal")
        self.export_report_btn.configure(state="normal")

    def _repair_target(self) -> None:
        p2 = Path(self.patch_entry.get().strip())
        if not p2.is_file():
            return
        save_path_str = filedialog.asksaveasfilename(
            title="Save Repaired Mobile-Compatible MP4",
            initialdir=str(p2.parent),
            initialfile=f"{p2.stem}_repaired{p2.suffix}",
            defaultextension=p2.suffix,
            filetypes=[("MP4 / MOV files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
        )
        if not save_path_str:
            return
        out_path = Path(save_path_str)
        try:
            repair_for_mobile(p2, out_path)
            messagebox.showinfo(
                "Repair Complete",
                f"Repaired file saved to:\n{out_path}\n\n"
                "Target path updated to repaired file — running analysis.",
            )
            self.patch_entry.delete(0, "end")
            self.patch_entry.insert(0, str(out_path))
            self._run_analysis()
        except Exception as exc:
            messagebox.showerror("Repair Failed", str(exc))

    def _save_diag_log(self) -> None:
        p1 = Path(self.orig_entry.get().strip())
        p2 = Path(self.patch_entry.get().strip())
        if not p2.is_file():
            return
        save_path_str = filedialog.asksaveasfilename(
            title="Save Diagnostic Log",
            defaultextension=".log",
            initialfile=f"diagnostic_{p2.stem}.log",
            filetypes=[("Log files", "*.log"), ("JSON files", "*.json")],
        )
        if not save_path_str:
            return
        try:
            s = getattr(self.master, "settings", None)
            mask = getattr(s, "mask_diagnostic_paths", True) if s else True
            export_diagnostic_log(
                Path(save_path_str),
                target_file=p2,
                source_file=p1 if p1.is_file() else None,
                mask_paths=mask,
            )
            messagebox.showinfo("Export Complete", f"Diagnostic log saved to:\n{save_path_str}")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))

    def _export_json(self) -> None:
        if not self._diff_result:
            return
        out_dir_str = filedialog.askdirectory(title="Select Folder to Export JSON Artifacts")
        if not out_dir_str:
            return
        out_dir = Path(out_dir_str)
        try:
            export_diff_artifacts(self._diff_result, out_dir)
            messagebox.showinfo(
                "Export Complete",
                f"Exported before.json, after.json, and diff.json to:\n{out_dir}",
            )
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))

    def _export_report(self) -> None:
        res = self._diff_result
        if res is None or res.before is None or res.after is None:
            return
        save_path_str = filedialog.asksaveasfilename(
            title="Save Forensic Report",
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt")],
        )
        if not save_path_str:
            return
        save_path = Path(save_path_str)
        orig_name = Path(res.before.file_path).name
        patch_name = Path(res.after.file_path).name
        v_match = "PASS (Bit-exact)" if res.video_payload_match else "FAIL (Modified)"
        trailing = f"{res.after.trailing_data_size} bytes"

        md_lines = [
            f"# MP4 Forensic Report: {orig_name} vs {patch_name}",
            "",
            "## 1. Verified Findings",
            f"- **Video Payload Integrity**: {v_match}",
            f"- **Entire mdat Box**: {'MATCH' if res.mdat_match else 'CHANGED'}",
            f"- **Audio Samples**: {'MATCH' if res.audio_payload_match else 'CHANGED'}",
            f"- **Trailing / Ghost Data**: {trailing}",
            "",
            "## 2. Server Behavior Status",
            (
                "- **TikTok 1080p Bypass**: NOT VERIFIED "
                "(Platform server behavior cannot be locally verified)"
            ),
            "",
            "## 3. Observed Atom Differences",
            f"- **Changed Atoms**: `{', '.join(res.changed_atoms) or 'None'}`",
            "",
            "### Semantic Differences",
        ]
        for s in res.semantic_diffs:
            md_lines.append(f"- **{s.target}** `{s.field}`: `{s.old_value}` → `{s.new_value}`")
        md_lines.extend(
            [
                "",
                "### Binary Differences (First 100 Spans)",
                "| Offset | Length | Atom Path | Old Hex | New Hex |",
                "|---|---|---|---|---|",
            ]
        )
        for b in res.byte_diffs[:100]:
            md_lines.append(
                f"| `0x{b.offset:08x}` | {b.length} | `{b.atom_path}` | "
                f"`{b.old_bytes_hex}` | `{b.new_bytes_hex}` |"
            )
        try:
            save_path.write_text("\n".join(md_lines), encoding="utf-8")
            messagebox.showinfo("Export Complete", f"Saved forensic report to:\n{save_path}")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))

