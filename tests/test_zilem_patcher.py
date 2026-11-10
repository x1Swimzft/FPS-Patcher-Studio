"""Tests for the X1T Zilem container-only preset."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

from fps_patcher.config import Settings
from fps_patcher.core.errors import VerifyError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import LogEvent, PatchRequest
from fps_patcher.core.patcher import output_base_for, patch
from fps_patcher.core.strategies import (
    UI_PRESETS,
    VISIBLE_PRESET_KEYS,
    get_strategy,
    migrate_strategy_name,
)
from fps_patcher.core.zilem_patcher import (
    SILENCE_FRAME,
    ZILEM_TAG,
    ZilemSourceError,
    build_zilem,
    inspect_zilem_source,
    verify_zilem_output,
)

_REFERENCE_TAG = "TikQuick Quality Method - https://tikquick.online/ - v25 - Orion"
_TRAILER_SIZE = 71


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def _encode(
    ff: FFmpegPaths,
    out: Path,
    *,
    video_codec: str = "libx264",
    audio: bool = True,
    channels: int = 2,
    sample_rate: int = 48000,
    extra: tuple[str, ...] = (),
) -> Path:
    cmd = [
        str(ff.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=30:duration=1",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1"]
    cmd += ["-c:v", video_codec, "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-ar", str(sample_rate), "-ac", str(channels)]
    cmd += [*extra, str(out)]
    _run(cmd)
    return out


def _has_encoder(ff: FFmpegPaths, name: str) -> bool:
    proc = subprocess.run(
        [str(ff.ffmpeg), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return name in proc.stdout


def _top_level_boxes(data: bytes | bytearray) -> list[tuple[int, int, bytes]]:
    boxes: list[tuple[int, int, bytes]] = []
    position = 0
    while position + 8 <= len(data):
        size, atom_type = struct.unpack_from(">I4s", data, position)
        if size < 8 or position + size > len(data):
            break
        boxes.append((position, size, atom_type))
        position += size
    return boxes


def _mdat_offsets(data: bytes | bytearray) -> list[tuple[int, int]]:
    return [
        (offset, size)
        for offset, size, atom_type in _top_level_boxes(data)
        if atom_type == b"mdat"
    ]


@pytest.fixture(scope="module")
def zilem_source(ff: FFmpegPaths, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("zilem") / "source.mp4"
    return _encode(ff, path)


def test_inspect_accepts_h264_aac_48k_stereo(zilem_source: Path) -> None:
    info = inspect_zilem_source(zilem_source)

    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.audio_sample_rate == 48000
    assert info.audio_channels == 2
    assert info.audio_samples > 0
    assert info.audio_chunks > 0
    assert info.video_samples > 0


def test_build_and_verify_round_trip(
    zilem_source: Path, tmp_path: Path
) -> None:
    source_bytes = zilem_source.read_bytes()
    out = tmp_path / "out.mp4"

    stats = build_zilem(zilem_source, out)
    verify_zilem_output(zilem_source, out)

    data = out.read_bytes()
    assert stats.output_size == len(data)
    assert stats.audio_samples_after == stats.audio_samples_before + 17
    assert stats.audio_chunks_after == stats.audio_chunks_before + 2
    assert stats.new_track_id >= 3
    assert stats.tag == ZILEM_TAG
    source_top = _top_level_boxes(source_bytes)
    source_moov = next(
        (offset, size) for offset, size, atom_type in source_top if atom_type == b"moov"
    )
    old_offset, old_size = source_moov
    assert data[:old_offset] == source_bytes[:old_offset]
    assert data[old_offset : old_offset + 4] == struct.pack(">I", old_size)
    assert data[old_offset + 4 : old_offset + 8] == b"free"
    assert (
        data[old_offset + 8 : old_offset + old_size]
        == source_bytes[old_offset + 8 : old_offset + old_size]
    )
    top = _top_level_boxes(data)
    mdat2_offset, mdat2_size, mdat2_type = top[-2]
    assert mdat2_type == b"mdat"
    assert mdat2_offset == len(source_bytes)
    assert mdat2_size == 8 + len(SILENCE_FRAME) * 17
    assert top[-1][2] == b"moov"
    assert top[-1][0] + top[-1][1] == len(data)
    assert data[mdat2_offset + 8 : mdat2_offset + mdat2_size] == SILENCE_FRAME * 17


def test_reference_tag_override(
    zilem_source: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out, tag=_REFERENCE_TAG)
    verify_zilem_output(zilem_source, out, tag=_REFERENCE_TAG)
    assert _REFERENCE_TAG.encode() in out.read_bytes()


def test_golden_fixture_matches_reference(tmp_path: Path) -> None:
    source = os.environ.get("FPS_ZILEM_SOURCE")
    reference = os.environ.get("FPS_ZILEM_REFERENCE")
    if not source or not reference:
        pytest.skip("set FPS_ZILEM_SOURCE and FPS_ZILEM_REFERENCE for the golden test")
    source_path = Path(source)
    reference_path = Path(reference)
    if not source_path.is_file() or not reference_path.is_file():
        pytest.skip("golden Zilem fixture files are missing")

    expected = reference_path.read_bytes()
    assert expected[-_TRAILER_SIZE :][4:8] == b"free"
    out = tmp_path / "golden.mp4"
    build_zilem(source_path, out, tag=_REFERENCE_TAG)
    verify_zilem_output(source_path, out, tag=_REFERENCE_TAG)

    assert out.read_bytes() == expected[:-_TRAILER_SIZE]


def test_source_media_is_not_touched(zilem_source: Path, tmp_path: Path) -> None:
    before = hashlib.sha256(zilem_source.read_bytes()).hexdigest()
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out)
    assert hashlib.sha256(zilem_source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"audio": False}, "no audio track"),
        ({"channels": 1}, "48 kHz stereo"),
        ({"sample_rate": 44100}, "48 kHz stereo"),
    ],
)
def test_rejects_incompatible_audio(
    ff: FFmpegPaths,
    tmp_path: Path,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    src = _encode(ff, tmp_path / "bad.mp4", **kwargs)
    with pytest.raises(ZilemSourceError, match=message):
        inspect_zilem_source(src)


@pytest.mark.parametrize("extension", [".txt", ".ts", ".mkv"])
def test_rejects_non_iso_bmff(tmp_path: Path, extension: str) -> None:
    src = tmp_path / f"not-video{extension}"
    src.write_bytes(b"not an mp4 file")
    with pytest.raises(ZilemSourceError, match="MP4|moov|box"):
        inspect_zilem_source(src)


def test_rejects_fragmented_mp4(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = _encode(
        ff,
        tmp_path / "fragmented.mp4",
        extra=("-movflags", "frag_keyframe+empty_moov"),
    )
    with pytest.raises(ZilemSourceError, match="[Ff]ragmented"):
        inspect_zilem_source(src)


def test_rejects_hevc(ff: FFmpegPaths, tmp_path: Path) -> None:
    if not _has_encoder(ff, "libx265"):
        pytest.skip("libx265 encoder not available")
    src = _encode(ff, tmp_path / "hevc.mp4", video_codec="libx265", audio=True)
    with pytest.raises(ZilemSourceError, match="H.264"):
        inspect_zilem_source(src)


def test_rejects_second_audio_track(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "two-audio.mp4"
    _run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=30:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(src),
        ]
    )
    with pytest.raises(ZilemSourceError, match="one audio track"):
        inspect_zilem_source(src)


def test_build_rejects_output_equal_to_source(zilem_source: Path) -> None:
    with pytest.raises(ZilemSourceError, match="output path equals source"):
        build_zilem(zilem_source, zilem_source)


def test_verify_rejects_changed_media_byte(zilem_source: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out)
    data = bytearray(out.read_bytes())
    offset, size = _mdat_offsets(data)[0]
    data[offset + size // 2] ^= 0xFF
    out.write_bytes(data)
    with pytest.raises(VerifyError, match="media data changed"):
        verify_zilem_output(zilem_source, out)


def test_verify_rejects_wrong_tag(zilem_source: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out)
    data = out.read_bytes()
    assert ZILEM_TAG.encode() in data
    out.write_bytes(data.replace(ZILEM_TAG.encode(), b"X1T Zilem v2"))
    with pytest.raises(VerifyError, match="video tag mismatch"):
        verify_zilem_output(zilem_source, out)


def test_verify_rejects_appended_trailer(zilem_source: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out)
    with out.open("ab") as handle:
        handle.write(b"\x00" * 71)
    with pytest.raises(VerifyError, match="output size|trailing bytes"):
        verify_zilem_output(zilem_source, out)


def test_verify_rejects_changed_old_moov_payload(
    zilem_source: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.mp4"
    build_zilem(zilem_source, out)
    data = bytearray(out.read_bytes())
    source_moov = next(
        (offset, size)
        for offset, size, atom_type in _top_level_boxes(zilem_source.read_bytes())
        if atom_type == b"moov"
    )
    old_moov = next(
        (offset, size)
        for offset, size, atom_type in _top_level_boxes(data)
        if atom_type == b"free" and (offset, size) == source_moov
    )
    data[old_moov[0] + 16] ^= 0xFF
    out.write_bytes(data)
    with pytest.raises(VerifyError, match="old moov payload changed"):
        verify_zilem_output(zilem_source, out)


def test_zilem_is_the_default_and_visible_first() -> None:
    assert Settings().strategy == "zilem"
    assert VISIBLE_PRESET_KEYS[0] == "zilem"
    assert get_strategy("zilem").label == "X1T Zilem"
    assert get_strategy("x1t-zilem").name == "zilem"
    assert all(
        preset.label.startswith("X1T")
        for preset in (UI_PRESETS[key] for key in VISIBLE_PRESET_KEYS)
    )
    assert migrate_strategy_name("zilem") == ("zilem", None)
    assert migrate_strategy_name("x1t-zilem") == ("zilem", None)
    assert migrate_strategy_name("tiktok-ts-remux") == ("tiktok-ts-remux", None)


def test_zilem_migration_only_touches_the_old_default() -> None:
    old_default = Settings(strategy="tiktok-ts-remux")
    old_default._clamp()
    assert old_default.strategy == "zilem"
    assert old_default.zilem_default_migrated is True

    for saved in ("tiktok-ts", "tiktok-ts-1080", "bxd-clean", "bxd-pc"):
        settings = Settings(strategy=saved)
        settings._clamp()
        assert settings.strategy == saved
        assert settings.zilem_default_migrated is True

    # A later explicit return to X1T Remux is preserved once migration ran.
    explicit = Settings(strategy="tiktok-ts-remux", zilem_default_migrated=True)
    explicit._clamp()
    assert explicit.strategy == "tiktok-ts-remux"


def test_zilem_migration_persists_once(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"strategy": "tiktok-ts-remux"}), encoding="utf-8")

    migrated = Settings.load(path)
    assert migrated.strategy == "zilem"
    assert migrated.zilem_default_migrated is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["strategy"] == "zilem"
    assert saved["zilem_default_migrated"] is True


def test_zilem_migration_keeps_other_saved_preset(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"strategy": "bxd-clean"}), encoding="utf-8")

    loaded = Settings.load(path)
    assert loaded.strategy == "bxd-clean"
    assert loaded.zilem_default_migrated is True


def test_zilem_output_name_ignores_target_fps(tmp_path: Path) -> None:
    req = PatchRequest(
        src=tmp_path / "clip.mov",
        out_dir=tmp_path / "out",
        timescale=120000,
        strategy="zilem",
    )
    assert output_base_for(req).name == "clip_zilem.mp4"


def test_patch_runs_zilem_branch(
    ff: FFmpegPaths, zilem_source: Path, tmp_path: Path
) -> None:
    events: list[object] = []
    req = PatchRequest(
        src=zilem_source,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="zilem",
        auto_normalize_audio=True,
        auto_cap_bitrate=True,
        fix_color_tag=True,
        scrub_metadata=True,
    )
    result = patch(req, ff, events.append)
    messages = [event.message for event in events if isinstance(event, LogEvent)]

    assert result.output.name == "source_zilem.mp4"
    assert result.output.exists()
    assert result.after.codec == "h264"
    assert result.after.audio_codec == "aac"
    assert result.after.stream_count == 3
    assert not any(message.startswith("[PREFLIGHT]") for message in messages)
    assert any("[COLOR] skipped: X1T Zilem" in message for message in messages)
    assert any("[VERIFY] Zilem container fingerprint PASS" in message for message in messages)
    verify_zilem_output(zilem_source, result.output)
