"""BXD audio payload verification (ghost samples excluded) + experimental batch summary."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from conftest import _make_clip
from test_app import _wait_for  # noqa: I001

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.forensic_analyzer import AtomNode, MP4ForensicAnalyzer, compare_mp4_files
from fps_patcher.core.models import (
    Event,
    LogEvent,
    PatchDoneEvent,
    PatchRequest,
    PatchResult,
    ProbeDoneEvent,
    VideoInfo,
)
from fps_patcher.core.patcher import patch
from fps_patcher.core.verifier import verify_payload_integrity


def _bxd(src: Path, out_dir: Path) -> PatchResult:
    req = PatchRequest(
        src=src, out_dir=out_dir, timescale=60000, strategy="bxd-experimental"
    )
    return patch(req, paths=None, emit=lambda e: None)


def _audio_first_chunk_offset(path: Path) -> int:
    report = MP4ForensicAnalyzer(path.read_bytes(), str(path)).parse()
    moov = next(n for n in report.atom_tree if n.type_str == "moov")

    def find(node: AtomNode, typ: str) -> AtomNode | None:
        if node.type_str == typ:
            return node
        for ch in node.children:
            hit = find(ch, typ)
            if hit:
                return hit
        return None

    for trak in (n for n in moov.children if n.type_str == "trak"):
        hdlr = find(trak, "hdlr")
        if hdlr and str(hdlr.fields.get("handler_type", "")).strip() == "soun":
            stco = find(trak, "stco")
            assert stco is not None
            return int(stco.fields["first_chunk_offsets"][0])
    raise AssertionError("no audio track")


def test_bxd_audio_payload_pass_ghosts_reported(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = _make_clip(ff, tmp_path / "src.mp4", "30", audio=True)
    res = _bxd(src, tmp_path / "out")

    diff = compare_mp4_files(src, res.output)
    assert diff.audio_ghost_samples > 0
    assert diff.audio_payload_match is True

    report = verify_payload_integrity(src, res.output)
    assert report["audio payload"] == "PASS"
    assert report["video payload"] == "PASS"
    assert report["audio ghost samples"] == "EXPERIMENTAL"
    assert report["trailing data"] == "EXPERIMENTAL"


def test_bxd_audio_payload_fails_when_real_sample_changed(
    ff: FFmpegPaths, tmp_path: Path
) -> None:
    src = _make_clip(ff, tmp_path / "src.mp4", "30", audio=True)
    res = _bxd(src, tmp_path / "out")

    data = bytearray(res.output.read_bytes())
    off = _audio_first_chunk_offset(res.output)
    data[off] ^= 0xFF
    tampered = tmp_path / "tampered.mp4"
    tampered.write_bytes(bytes(data))

    report = verify_payload_integrity(src, tampered)
    assert report["audio payload"] == "FAIL"


def test_standard_patch_has_no_ghost_row_and_not_experimental(
    ff: FFmpegPaths, tmp_path: Path
) -> None:
    src = _make_clip(ff, tmp_path / "src.mp4", "30", audio=True)
    req = PatchRequest(
        src=src, out_dir=tmp_path / "out", timescale=60000, strategy="direct-atom"
    )
    res = patch(req, paths=None, emit=lambda e: None)
    assert res.experimental is False
    report = verify_payload_integrity(src, res.output)
    assert report["audio payload"] == "PASS"
    assert "audio ghost samples" not in report


def test_bxd_patch_result_marked_experimental(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = _make_clip(ff, tmp_path / "src.mp4", "30", audio=True)
    assert _bxd(src, tmp_path / "out").experimental is True


def _dummy_info(path: Path, timescale: int) -> VideoInfo:
    return VideoInfo(
        path=path,
        codec="h264",
        width=320,
        height=240,
        avg_fps=Fraction(30),
        r_fps=Fraction(30),
        duration_s=1.0,
        timescale=timescale,
        nb_frames=30,
        has_audio=True,
        stream_count=2,
    )


@pytest.mark.parametrize("experimental", [True, False])
def test_batch_summary_experimental_wording(
    clip30: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, experimental: bool
) -> None:
    def mock_patch(req: PatchRequest, *args: object, **kwargs: object) -> PatchResult:
        info = _dummy_info(req.src, req.timescale)
        return PatchResult(
            src=req.src,
            output=req.src,
            before=info,
            after=info,
            elapsed_s=0.01,
            experimental=experimental,
        )

    monkeypatch.setattr("fps_patcher.app.controller.patch", mock_patch)
    ctrl = AppController(Settings(output_dir=str(tmp_path), overwrite=True, auto_rename=False))
    ctrl.init_ffmpeg()
    ctrl.load_file(clip30)
    _wait_for(ctrl, ProbeDoneEvent)
    ctrl.start_patch(60000, "timescale")
    events: list[Event] = _wait_for(ctrl, PatchDoneEvent)

    summary = next(
        e for e in events if isinstance(e, LogEvent) and e.message.startswith("Batch summary")
    )
    if experimental:
        assert summary.message == "Batch summary: 0 ok, 1 done (experimental), 0 failed"
        assert summary.level == "WARN"
    else:
        assert summary.message == "Batch summary: 1 ok, 0 failed"
        assert summary.level == "OK"
