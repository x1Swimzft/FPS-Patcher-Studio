"""Integration test: generates video via ffmpeg lavfi, remuxes, and probes with ffprobe."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import LogEvent, PatchRequest, ProgressEvent
from fps_patcher.core.patcher import patch
from fps_patcher.core.prober import probe


def test_integration_lavfi_generate_patch_and_probe(ff: FFmpegPaths, tmp_path: Path) -> None:
    # 1. Generate a source clip using ffmpeg lavfi testsrc + sine audio
    src_file = tmp_path / "lavfi_source_30fps.mp4"
    gen_cmd = [
        str(ff.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=30:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(src_file),
    ]
    subprocess.run(gen_cmd, check=True)
    assert src_file.is_file(), "Source clip was not created by lavfi"

    # 2. Probe the initial clip using real ffprobe
    initial_info = probe(src_file, ff.ffprobe)
    assert initial_info.codec == "h264"
    assert initial_info.width == 640
    assert initial_info.height == 360
    assert round(initial_info.fps) == 30
    assert initial_info.has_audio is True
    assert initial_info.timescale > 0

    # 3. Patch container metadata via stream copy (timescale 60000)
    target_timescale = 60000
    events: list[LogEvent | ProgressEvent] = []
    out_dir = tmp_path / "output"
    req = PatchRequest(
        src=src_file,
        out_dir=out_dir,
        timescale=target_timescale,
        strategy="timescale",
    )
    result = patch(req, ff, events.append)

    # 4. Verify output file exists and is located in the target directory
    output_path = result.output
    assert output_path.is_file(), f"Output file missing: {output_path}"
    assert output_path.parent == out_dir

    # 5. Assert patched timescale via real ffprobe directly on the output file
    verified_info = probe(output_path, ff.ffprobe)
    assert verified_info.timescale == target_timescale, (
        f"Expected timescale {target_timescale}, got {verified_info.timescale}"
    )

    # 6. Prove stream copy (no re-encode occurred)
    assert verified_info.codec == initial_info.codec
    assert verified_info.width == initial_info.width
    assert verified_info.height == initial_info.height
    assert verified_info.stream_count == initial_info.stream_count
    assert verified_info.has_audio == initial_info.has_audio
    assert verified_info.nb_frames == initial_info.nb_frames
    assert abs(verified_info.duration_s - initial_info.duration_s) < 0.1

    # 7. Progress events were emitted reaching 1.0
    progress_fractions = [e.fraction for e in events if isinstance(e, ProgressEvent)]
    assert len(progress_fractions) > 0
    assert progress_fractions[-1] == 1.0
