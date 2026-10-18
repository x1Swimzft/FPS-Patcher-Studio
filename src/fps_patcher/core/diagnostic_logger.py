"""Diagnostic report builder, table summarizer, path masker, and auto-rotating log writer."""

from __future__ import annotations

import getpass
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import app_data_dir
from .forensic_analyzer import AtomNode, MP4ForensicAnalyzer
from .verifier import (
    verify_atom_structure,
    verify_mobile_compatibility,
    verify_offsets,
    verify_sample_tables,
)

MAX_AUTO_LOG_FILES = 20
MAX_AUTO_LOGS = MAX_AUTO_LOG_FILES
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB budget ceiling


def logs_dir() -> Path:
    """Return cross-platform diagnostic logs directory."""
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mask_sensitive_text(
    text: str, mask_paths: bool = True, *, mask_enabled: bool | None = None
) -> str:
    """Mask user home directory, UNC paths, and username occurrences."""
    eff_mask = mask_enabled if mask_enabled is not None else mask_paths
    if not eff_mask or not text:
        return text

    out = text
    try:
        home = str(Path.home())
        home_fwd = home.replace("\\", "/")
        home_bck = home.replace("/", "\\")
        for variant in (home_bck, home_fwd):
            if variant:
                out = re.sub(re.escape(variant), "<USER_HOME>", out, flags=re.IGNORECASE)
    except Exception:
        pass

    # Mask UNC paths: \\server\share\... or //server/share/...
    out = re.sub(
        r"(\\\\|//)[^\\/:\s]+(\\|/)[^\\/:\s]+",
        r"\1<SERVER>\2<SHARE>",
        out,
    )

    # Mask explicit Windows/POSIX user profile patterns
    out = re.sub(
        r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\s\"']+", r"\1<USER>", out, flags=re.IGNORECASE
    )
    out = re.sub(r"(/home/|/Users/)[^/\s\"']+", r"\1<USER>", out)

    # Mask standalone username if >= 3 chars
    candidates: set[str] = set()
    try:
        u1 = getpass.getuser()
        if u1 and len(u1) >= 3:
            candidates.add(u1)
    except Exception:
        pass
    try:
        u2 = Path.home().name
        if u2 and len(u2) >= 3:
            candidates.add(u2)
    except Exception:
        pass

    for username in candidates:
        out = re.sub(re.escape(username), "<USER>", out, flags=re.IGNORECASE)

    return out


def summarize_int_list(
    values: list[int],
    head: int = 25,
    tail: int = 25,
    anomalies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize large sample/offset arrays so diagnostic logs stay compact (<5 MB)."""
    cnt = len(values)
    if cnt == 0:
        return {"count": 0, "min": 0, "max": 0, "sum": 0, "head": [], "tail": [], "truncated": 0}
    summary: dict[str, Any] = {
        "count": cnt,
        "min": min(values),
        "max": max(values),
        "sum": sum(values),
        "head": values[:head],
        "tail": values[-tail:] if cnt > head else [],
        "truncated": max(0, cnt - (head + tail)),
    }
    if anomalies:
        summary["anomalies"] = anomalies[:50]
    return summary


def _compact_atom_tree(nodes: list[AtomNode], depth: int = 0) -> list[dict[str, Any]]:
    """Serialize atom tree with compact field summaries."""
    out: list[dict[str, Any]] = []
    for n in nodes:
        compact_fields: dict[str, Any] = {}
        for k, v in n.fields.items():
            if isinstance(v, list) and len(v) > 50:
                compact_fields[k] = {
                    "count": len(v),
                    "head": v[:20],
                    "tail": v[-20:],
                    "truncated": True,
                }
            else:
                compact_fields[k] = v
        out.append(
            {
                "type": n.type_str,
                "start": n.start,
                "size": n.size,
                "header_size": n.header_size,
                "version": n.version,
                "fields": compact_fields,
                "children": _compact_atom_tree(n.children, depth + 1) if depth < 6 else [],
            }
        )
    return out


def build_diagnostic_report(
    file_path: Path | None = None,
    console_lines: list[str] | None = None,
    orig_path: Path | None = None,
    mask_paths: bool = True,
    *,
    target_file: Path | None = None,
    source_file: Path | None = None,
    preset: str | None = None,
    target_timescale: int | None = None,
) -> dict[str, Any]:
    """Build a comprehensive diagnostic report dictionary for a patched/inspected MP4."""
    eff_target = target_file if target_file is not None else file_path
    eff_source = source_file if source_file is not None else orig_path
    now_iso = datetime.now().isoformat(timespec="seconds")
    report: dict[str, Any] = {
        "generated_at": now_iso,
        "target_file": mask_sensitive_text(str(eff_target), mask_paths) if eff_target else None,
        "source_file": mask_sensitive_text(str(eff_source), mask_paths) if eff_source else None,
        "preset": preset,
        "target_timescale": target_timescale,
        "mobile_compatibility": None,
        "structural_validation": None,
        "offset_validation": None,
        "sample_table_validation": None,
        "repair_recommendations": [],
        "tracks": [],
        "atom_tree": [],
        "console_tail": [
            mask_sensitive_text(line, mask_paths) for line in (console_lines or [])[-500:]
        ],
    }

    if eff_target is not None and eff_target.is_file():
        try:
            raw = eff_target.read_bytes()
            struct_res = verify_atom_structure(raw)
            ok_off, off_issues = verify_offsets(raw)
            ok_tbl, tbl_issues = verify_sample_tables(raw)
            mob_res = verify_mobile_compatibility(raw)

            report["structural_validation"] = {
                "status": struct_res.status,
                "is_valid": struct_res.is_valid,
                "is_experimental": struct_res.is_experimental,
                "faststart": struct_res.faststart,
                "has_trailing_data": struct_res.has_trailing_data,
                "trailing_bytes_count": struct_res.trailing_bytes_count,
                "details": struct_res.details[:50],
            }
            report["offset_validation"] = {
                "valid": ok_off,
                "issue_count": len(off_issues),
                "issues": off_issues[:50],
            }
            report["sample_table_validation"] = {
                "valid": ok_tbl,
                "issue_count": len(tbl_issues),
                "issues": tbl_issues[:50],
            }
            report["mobile_compatibility"] = {
                "compatible": mob_res.compatible,
                "status": mob_res.status,
                "faststart": mob_res.faststart,
                "has_mvex": mob_res.has_mvex,
                "issues": mob_res.issues,
                "warnings": mob_res.warnings,
            }

            # Build actionable repair recommendations
            recs: list[str] = []
            if not mob_res.compatible:
                recs.append(
                    "Use 'Repair for Mobile' in FPS Patcher Studio to strip BXD ghost audio "
                    "entries, remove unboxed trailing bytes, reconstruct video edts/elst from "
                    "ctts, and restore valid mvhd/tkhd durations."
                )
                recs.append(
                    "For future patches intended for iOS/Android, select 'Bxd For Mobile', "
                    "'Bxd Hybrid', or 'Bxd Clean' preset instead of 'Bxd For PC'."
                )
            report["repair_recommendations"] = recs

            analyzer = MP4ForensicAnalyzer(raw, str(eff_target))
            f_rep = analyzer.parse()
            report["file_size"] = f_rep.file_size
            report["mdat_offset"] = f_rep.mdat_offset
            report["mdat_size"] = f_rep.mdat_size
            report["mdat_payload_sha256"] = f_rep.mdat_payload_sha256
            report["summary_fields"] = f_rep.summary_fields
            report["atom_tree"] = _compact_atom_tree(f_rep.atom_tree)

            for t in f_rep.tracks:
                report["tracks"].append(
                    {
                        "track_id": t.track_id,
                        "handler_type": t.handler_type,
                        "codec": t.codec,
                        "timescale": t.timescale,
                        "duration_track": t.duration_track,
                        "duration_movie": t.duration_movie,
                        "width": t.width,
                        "height": t.height,
                        "sample_count": t.sample_count,
                        "sample_payload_sha256": t.sample_payload_sha256,
                        "stts_summary": {
                            "entry_count": len(t.stts_entries),
                            "head": t.stts_entries[:25],
                            "tail": t.stts_entries[-25:] if len(t.stts_entries) > 25 else [],
                        },
                        "ctts_summary": {
                            "entry_count": len(t.ctts_entries),
                            "head": t.ctts_entries[:25],
                            "tail": t.ctts_entries[-25:] if len(t.ctts_entries) > 25 else [],
                        },
                        "elst_entries": t.elst_entries[:25],
                    }
                )
        except Exception as exc:
            report["parse_error"] = mask_sensitive_text(str(exc), mask_paths)

    return report


def format_diagnostic_text(report: dict[str, Any]) -> str:
    """Format diagnostic report dictionary into readable plain text (<5 MB)."""
    lines: list[str] = [
        "======================================================================",
        "FPS PATCHER STUDIO — DIAGNOSTIC & MOBILE COMPATIBILITY REPORT",
        "======================================================================",
        f"Generated At : {report.get('generated_at')}",
        f"Target File  : {report.get('target_file') or 'N/A'}",
        f"Source File  : {report.get('source_file') or 'N/A'}",
    ]
    if report.get("preset"):
        lines.append(
            f"Preset       : {report.get('preset')} (timescale={report.get('target_timescale')})"
        )
    if "file_size" in report:
        lines.append(f"File Size    : {report['file_size']:,} bytes")
        lines.append(
            f"mdat Bounds  : offset={report.get('mdat_offset')}, size={report.get('mdat_size')}, "
            f"sha256={report.get('mdat_payload_sha256')}"
        )

    mob = report.get("mobile_compatibility")
    if isinstance(mob, dict):
        lines.append("")
        lines.append("--- MOBILE COMPATIBILITY CHECK & ISO-BMFF DIAGNOSIS ---")
        lines.append(f"Status       : {mob.get('status')}")
        lines.append(f"Faststart    : {'YES (moov before mdat)' if mob.get('faststart') else 'NO'}")
        issues = mob.get("issues") or []
        if issues:
            lines.append("Issues Found :")
            for idx, iss in enumerate(issues, start=1):
                lines.append(f"  {idx}. {iss}")
        else:
            lines.append("Issues Found : None (all structural & timing checks passed)")
        warns = mob.get("warnings") or []
        for w in warns:
            lines.append(f"Warning      : {w}")

    recs = report.get("repair_recommendations") or []
    if recs:
        lines.append("")
        lines.append("--- RECOMMENDED FIXES ---")
        for r in recs:
            lines.append(f"* {r}")

    tracks = report.get("tracks") or []
    if tracks:
        lines.append("")
        lines.append("--- TRACK SUMMARY ---")
        for tr in tracks:
            sha_short = str(tr["sample_payload_sha256"])[:16]
            lines.append(
                f"Track #{tr['track_id']} [{tr['handler_type']}] codec={tr['codec']} "
                f"ts={tr['timescale']} mdhd_dur={tr['duration_track']} "
                f"tkhd_dur={tr['duration_movie']} samples={tr['sample_count']} "
                f"payload_sha256={sha_short}..."
            )
            if tr.get("elst_entries"):
                lines.append(f"  elst: {tr['elst_entries']}")

    atom_tree = report.get("atom_tree") or []
    if atom_tree:
        lines.append("")
        lines.append("--- TOP-LEVEL ATOM LAYOUT ---")
        for node in atom_tree:
            lines.append(
                f"  [{node['type']}] start={node['start']} "
                f"size={node['size']} hdr={node['header_size']}"
            )

    c_tail = report.get("console_tail") or []
    if c_tail:
        lines.append("")
        lines.append("--- CONSOLE LOG TAIL ---")
        lines.extend(c_tail)

    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_LOG_BYTES:
        clipped = encoded[: MAX_LOG_BYTES - 128].decode("utf-8", errors="ignore")
        text = clipped + "\n...[TRUNCATED AT 5MB]...\n"
    return text


def _prune_auto_logs(directory: Path, max_files: int = MAX_AUTO_LOG_FILES) -> None:
    """Keep at most `max_files` auto-generated logs (`auto_patch_*`); preserve user logs."""
    auto_files = sorted(
        directory.glob("auto_patch_*.log"),
        key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name),
    )
    while len(auto_files) > max_files:
        oldest = auto_files.pop(0)
        oldest.unlink(missing_ok=True)


def auto_save_diagnostic_log(
    file_path: Path | None = None,
    console_lines: list[str] | None = None,
    orig_path: Path | None = None,
    mask_paths: bool = True,
    max_auto_files: int = MAX_AUTO_LOG_FILES,
    *,
    target_file: Path | None = None,
    source_file: Path | None = None,
    preset: str | None = None,
    target_timescale: int | None = None,
    log_dir: Path | None = None,
) -> Path:
    """Automatically save a diagnostic log in logs_dir() and rotate old auto_patch_* files."""
    d = log_dir if log_dir is not None else logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = d / f"auto_patch_{stamp}.log"
    rep = build_diagnostic_report(
        file_path=file_path,
        console_lines=console_lines,
        orig_path=orig_path,
        mask_paths=mask_paths,
        target_file=target_file,
        source_file=source_file,
        preset=preset,
        target_timescale=target_timescale,
    )
    target.write_text(format_diagnostic_text(rep), encoding="utf-8")
    _prune_auto_logs(d, max_files=max_auto_files)
    return target


def export_diagnostic_log(
    target_path: Path,
    file_path: Path | None = None,
    console_lines: list[str] | None = None,
    orig_path: Path | None = None,
    mask_paths: bool = True,
    *,
    target_file: Path | None = None,
    source_file: Path | None = None,
    preset: str | None = None,
    target_timescale: int | None = None,
) -> Path:
    """Export user-requested diagnostic log (.log or .json). Never deleted by auto-rotation."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    rep = build_diagnostic_report(
        file_path=file_path,
        console_lines=console_lines,
        orig_path=orig_path,
        mask_paths=mask_paths,
        target_file=target_file,
        source_file=source_file,
        preset=preset,
        target_timescale=target_timescale,
    )
    if target_path.suffix.lower() == ".json":
        raw_json = json.dumps(rep, indent=2, ensure_ascii=False)
        if len(raw_json.encode("utf-8")) > MAX_LOG_BYTES:
            rep["console_tail"] = (rep.get("console_tail") or [])[-100:]
            rep["atom_tree"] = []
            raw_json = json.dumps(rep, indent=2, ensure_ascii=False)
        target_path.write_text(raw_json, encoding="utf-8")
    else:
        target_path.write_text(format_diagnostic_text(rep), encoding="utf-8")
    return target_path
