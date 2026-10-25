"""Headless CLI: ``fps-patcher-studio --cli patch|probe|score``.

Import graph rule: nothing here may import PySide6/Qt or the UI packages, so the
CLI works from a service, a script, or a console-subsystem shim.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .config import Settings
from .core.errors import FFmpegNotFoundError, FPSPatcherError, PatchCancelledError
from .core.ffmpeg_locator import FFmpegPaths, locate
from .core.models import FPS_PRESETS, SUPPORTED_EXTENSIONS, LogEvent, PatchRequest, VideoInfo
from .core.patcher import patch
from .core.platform_profiles import evaluate_readiness, profile_ids
from .core.prober import probe

EXIT_OK = 0
EXIT_FILE_ERROR = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130

_PRESET_TIMESCALES = {value: timescale for value, timescale in FPS_PRESETS.items()}
_DEFAULT_TIMESCALE = 60000


def attach_console() -> None:
    """Windowed frozen build: borrow the parent console so CLI output is visible.

    A ``--windows-console-mode=disable`` EXE has no stdout. Callers that need the
    output must start it from a console (cmd/PowerShell); this reattaches and
    rebinds the streams. No-ops when a console is already present.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import WinDLL

        kernel32 = WinDLL("kernel32", use_last_error=True)
        if kernel32.GetConsoleWindow():
            return
        if not kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return
        for name in ("stdout", "stderr"):
            stream = open(  # noqa: SIM115 - rebound for the process lifetime
                "CONOUT$", "w", encoding="utf-8", buffering=1
            )
            setattr(sys, name, stream)
    except Exception:
        return


def _locate_ffmpeg(settings: Settings) -> FFmpegPaths | None:
    try:
        return locate(Path(settings.ffmpeg_dir) if settings.ffmpeg_dir else None)
    except FFmpegNotFoundError:
        return None


def _preset_timescale(value: str) -> int:
    key = value.strip().upper().replace("FPS", "").strip()
    key = f"{key} FPS" if key.isdigit() else value.strip().upper()
    if key in _PRESET_TIMESCALES:
        return _PRESET_TIMESCALES[key]
    raise argparse.ArgumentTypeError(
        f"unknown preset {value!r}; use one of {', '.join(_PRESET_TIMESCALES)}"
    )


def _info_dict(info: VideoInfo) -> dict[str, Any]:
    return {
        "path": str(info.path),
        "codec": info.codec,
        "width": info.width,
        "height": info.height,
        "fps": round(info.fps, 6),
        "duration_s": round(info.duration_s, 6),
        "timescale": info.timescale,
        "has_audio": info.has_audio,
        "audio_codec": info.audio_codec,
        "bit_rate": info.bit_rate,
        "color_primaries": info.color_primaries,
        "color_transfer": info.color_transfer,
        "color_space": info.color_space,
    }


def _emit_stderr(event: object) -> None:
    if isinstance(event, LogEvent):
        print(f"[{event.level}] {event.message}", file=sys.stderr)


def _supported(path: Path) -> bool:
    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
        return True
    print(f"error: unsupported file type: {path}", file=sys.stderr)
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fps-patcher-studio --cli",
        description=f"FPS Patcher Studio {__version__} headless CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    patch_cmd = sub.add_parser("patch", help="Patch one or more videos.")
    patch_cmd.add_argument("inputs", nargs="+", type=Path)
    patch_cmd.add_argument(
        "--preset",
        type=_preset_timescale,
        default=None,
        help="FPS preset: 60 or 120 (default: 60).",
    )
    patch_cmd.add_argument("--timescale", type=int, default=None, help="Explicit timescale.")
    patch_cmd.add_argument(
        "--strategy", default=None, help="Patch strategy (default from settings)."
    )
    patch_cmd.add_argument("--output", type=Path, default=None, help="Output directory.")
    patch_cmd.add_argument("--normalize-audio", action="store_true")
    patch_cmd.add_argument("--cap-bitrate", action="store_true")
    patch_cmd.add_argument("--tag-bt709", action="store_true", help="Tag untagged SDR as Rec.709.")
    patch_cmd.add_argument("--scrub-metadata", action="store_true")
    overwrite = patch_cmd.add_mutually_exclusive_group()
    overwrite.add_argument("--overwrite", action="store_true")
    overwrite.add_argument("--auto-rename", action="store_true")
    patch_cmd.add_argument("--json", action="store_true", help="Machine-readable stdout.")
    patch_cmd.set_defaults(func=_cmd_patch)

    probe_cmd = sub.add_parser("probe", help="Print probe metadata for one video.")
    probe_cmd.add_argument("input", type=Path)
    probe_cmd.add_argument("--json", action="store_true")
    probe_cmd.set_defaults(func=_cmd_probe)

    score_cmd = sub.add_parser("score", help="Readiness score for one video and profile.")
    score_cmd.add_argument("input", type=Path)
    score_cmd.add_argument("--profile", choices=profile_ids(), default="generic")
    score_cmd.add_argument("--json", action="store_true")
    score_cmd.set_defaults(func=_cmd_score)
    return parser


def _cmd_patch(args: argparse.Namespace, settings: Settings) -> int:
    ffmpeg = _locate_ffmpeg(settings)
    timescale = args.timescale or args.preset or _DEFAULT_TIMESCALE
    if timescale <= 0:
        print("error: --timescale must be positive", file=sys.stderr)
        return EXIT_USAGE
    strategy = args.strategy or settings.strategy
    overwrite = bool(args.overwrite)
    auto_rename = not overwrite

    cancel = threading.Event()

    def _cancel(_signum: int, _frame: Any) -> None:
        cancel.set()

    previous = signal.signal(signal.SIGINT, _cancel)
    files: list[dict[str, Any]] = []
    cancelled = False
    try:
        for source in args.inputs:
            if cancel.is_set():
                cancelled = True
                break
            entry: dict[str, Any] = {
                "input": str(source),
                "ok": False,
                "output": None,
                "error": None,
            }
            try:
                output_dir = args.output or (
                    Path(settings.output_dir) if settings.output_dir else source.parent
                )
                request = PatchRequest(
                    src=source,
                    out_dir=output_dir,
                    timescale=timescale,
                    strategy=strategy,
                    overwrite=overwrite,
                    auto_rename=auto_rename,
                    auto_normalize_audio=bool(args.normalize_audio),
                    auto_cap_bitrate=bool(args.cap_bitrate),
                    fix_color_tag=bool(args.tag_bt709),
                    scrub_metadata=bool(args.scrub_metadata),
                )
                result = patch(request, ffmpeg, _emit_stderr, cancel)
                entry["ok"] = True
                entry["output"] = str(result.output)
                if not args.json:
                    print(f"Patched: {result.output}")
            except PatchCancelledError:
                entry["error"] = "cancelled"
                files.append(entry)
                cancelled = True
                break
            except (FPSPatcherError, OSError) as exc:
                entry["error"] = str(exc)
                files.append(entry)
                print(f"Failed: {source}: {exc}", file=sys.stderr)
                continue
            files.append(entry)
    finally:
        signal.signal(signal.SIGINT, previous)

    ok = not cancelled and all(entry["ok"] for entry in files)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "command": "patch",
                    "version": __version__,
                    "cancelled": cancelled,
                    "files": files,
                },
                ensure_ascii=False,
            )
        )
    if cancelled:
        return EXIT_CANCELLED
    return EXIT_OK if ok else EXIT_FILE_ERROR


def _cmd_probe(args: argparse.Namespace, settings: Settings) -> int:
    if not _supported(args.input):
        return EXIT_USAGE
    ffmpeg = _locate_ffmpeg(settings)
    try:
        info = probe(args.input, ffmpeg.ffprobe if ffmpeg is not None else None)
    except (FPSPatcherError, OSError) as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return EXIT_FILE_ERROR
    if args.json:
        print(
            json.dumps(
                {"ok": True, "command": "probe", "file": _info_dict(info)},
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    print(f"{info.path}")
    print(f"  {info.codec} {info.width}x{info.height} {info.fps:.3f} fps")
    print(f"  duration {info.duration_s:.3f}s  timescale {info.timescale}")
    if info.has_audio:
        print(
            f"  audio {info.audio_codec} {info.audio_sample_rate or '?'} Hz "
            f"{info.audio_channels or '?'} ch"
        )
    print(
        f"  color {info.color_primaries or '-'} / {info.color_transfer or '-'} / "
        f"{info.color_space or '-'}"
    )
    return EXIT_OK


def _cmd_score(args: argparse.Namespace, settings: Settings) -> int:
    if not _supported(args.input):
        return EXIT_USAGE
    ffmpeg = _locate_ffmpeg(settings)
    try:
        info = probe(args.input, ffmpeg.ffprobe if ffmpeg is not None else None)
    except (FPSPatcherError, OSError) as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return EXIT_FILE_ERROR
    report = evaluate_readiness(info, args.profile)
    checks = [
        {
            "id": check.check_id,
            "label": check.label,
            "status": check.status,
            "severity": check.severity,
            "detail": check.detail,
            "measured": check.measured,
            "recommendation": check.recommendation,
            "evidence": check.evidence,
        }
        for check in report.checks
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "score",
                    "profile": report.profile_id,
                    "status": report.status,
                    "score": report.score,
                    "checks": checks,
                },
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    print(f"{args.profile}: {report.status} {report.score}/100")
    for check in report.checks:
        print(f"  {check.label}: {check.status} — {check.detail}")
        if check.recommendation:
            print(f"    {check.recommendation}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    """Run a CLI command. Returns the process exit code (0/1/2, 130 on cancel)."""
    attach_console()
    args = list(sys.argv[1:] if argv is None else argv)
    parsed = _parser().parse_args(args)  # exits 2 on usage errors
    try:
        return int(parsed.func(parsed, settings or Settings.load()))
    except KeyboardInterrupt:  # pragma: no cover - depends on console timing
        print("cancelled", file=sys.stderr)
        return EXIT_CANCELLED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
