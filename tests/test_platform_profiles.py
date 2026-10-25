"""Tests for platform profiles, readiness scoring, and UI badge integration."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from fps_patcher.config import Settings
from fps_patcher.core.models import LogEvent, VideoInfo
from fps_patcher.core.platform_profiles import (
    CRITICAL_UNKNOWN_SCORE_CAP,
    OPTIONAL_UNKNOWN_SCORE_CAP,
    PLATFORM_PROFILES,
    evaluate_readiness,
    get_profile,
)
from fps_patcher.core.prober import parse_probe
from fps_patcher.ui.strings import STRINGS, t


def _info(tmp_path: Path, **overrides: object) -> VideoInfo:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 1024)
    base: dict[str, object] = {
        "path": path,
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "avg_fps": Fraction(30),
        "r_fps": Fraction(30),
        "duration_s": 60.0,
        "timescale": 30000,
        "nb_frames": 1800,
        "has_audio": True,
        "stream_count": 2,
        "audio_codec": "aac",
        "bit_rate": 10_000_000,
        "audio_sample_rate": 48_000,
        "audio_channels": 2,
        "format_name": "mp4",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
        "color_space": "bt709",
        "pix_fmt": "yuv420p",
        "file_size_bytes": 1024,
    }
    base.update(overrides)
    return VideoInfo(**base)  # type: ignore[arg-type]


def test_profiles_cover_requested_platforms_and_labels() -> None:
    assert set(PLATFORM_PROFILES) == {"generic", "tiktok", "instagram", "youtube"}
    assert t("profile_tiktok", "en").startswith("X1T")
    assert t("profile_instagram", "en").startswith("X1T")
    assert t("profile_youtube", "en").startswith("X1T")
    assert get_profile("does-not-exist").profile_id == "generic"


def test_fully_known_tiktok_file_scores_100_ready(tmp_path: Path) -> None:
    report = evaluate_readiness(_info(tmp_path), "tiktok")
    assert report.score == 100
    assert report.status == "ready"
    assert report.unknown_checks == ()
    assert report.failed_checks == ()


def test_high_bitrate_is_heuristic_only_where_configured(tmp_path: Path) -> None:
    info = _info(tmp_path, bit_rate=30_000_000)
    tiktok = evaluate_readiness(info, "tiktok")
    youtube = evaluate_readiness(info, "youtube")

    bitrate = next(c for c in tiktok.checks if c.check_id == "bitrate")
    assert bitrate.status == "warning"
    assert bitrate.evidence == "heuristic"
    assert tiktok.score == 88
    assert tiktok.status == "review"

    # YouTube documents "no bitrate limit is required"; do not apply TikTok's cap.
    assert all(c.check_id != "bitrate" for c in youtube.checks)
    assert youtube.score == 100
    assert youtube.status == "ready"


def test_missing_metadata_never_scores_full_ready(tmp_path: Path) -> None:
    info = _info(
        tmp_path,
        width=0,
        height=0,
        avg_fps=Fraction(0),
        r_fps=Fraction(0),
        duration_s=0.0,
        bit_rate=None,
        audio_sample_rate=None,
        audio_channels=None,
        color_primaries=None,
        color_transfer=None,
        color_space=None,
    )
    report = evaluate_readiness(info, "tiktok")
    assert report.score <= CRITICAL_UNKNOWN_SCORE_CAP
    assert report.status == "review"
    unknown_ids = {c.check_id for c in report.unknown_checks}
    assert {"frame_geometry", "frame_rate", "duration", "bitrate", "audio"} <= unknown_ids


def test_optional_color_unknown_caps_score_but_not_status(tmp_path: Path) -> None:
    info = _info(
        tmp_path,
        color_primaries=None,
        color_transfer=None,
        color_space=None,
    )
    report = evaluate_readiness(info, "tiktok")
    assert report.score == OPTIONAL_UNKNOWN_SCORE_CAP
    assert report.status == "ready"
    assert "hdr_color" in {c.check_id for c in report.unknown_checks}


def test_missing_probe_info_returns_unknown(tmp_path: Path) -> None:
    report = evaluate_readiness(None, "tiktok")
    assert report.score == 0
    assert report.status == "unknown"
    assert report.checks[0].check_id == "probe"


def test_mov_is_a_recommendation_not_a_rejection(tmp_path: Path) -> None:
    report = evaluate_readiness(_info(tmp_path, format_name="mov"), "tiktok")
    container = next(c for c in report.checks if c.check_id == "container")
    assert container.status == "warning"
    assert container.severity == "recommendation"
    assert report.score == 97
    assert report.status == "ready"


def test_instagram_aspect_range_and_vertical_recommendation(tmp_path: Path) -> None:
    landscape = evaluate_readiness(_info(tmp_path, width=1920, height=1080), "instagram")
    geometry = next(c for c in landscape.checks if c.check_id == "frame_geometry")
    assert geometry.status == "warning"
    assert landscape.status == "review"

    ultra_wide = evaluate_readiness(_info(tmp_path, width=2560, height=1080), "instagram")
    geometry = next(c for c in ultra_wide.checks if c.check_id == "frame_geometry")
    assert geometry.status == "error"
    assert ultra_wide.status == "issues"
    assert ultra_wide.score <= 40


def test_youtube_landscape_and_long_duration_are_warnings(tmp_path: Path) -> None:
    landscape = evaluate_readiness(
        _info(tmp_path, width=1920, height=1080, duration_s=240.0), "youtube"
    )
    assert landscape.status == "review"
    checks = {c.check_id: c for c in landscape.checks}
    assert checks["frame_geometry"].status == "warning"
    assert checks["duration"].status == "warning"
    assert landscape.score == 76


def test_tiktok_out_of_range_fps_is_a_blocker(tmp_path: Path) -> None:
    info = _info(
        tmp_path,
        avg_fps=Fraction(120),
        r_fps=Fraction(120),
    )
    report = evaluate_readiness(info, "tiktok")
    frame_rate = next(c for c in report.checks if c.check_id == "frame_rate")
    assert frame_rate.status == "error"
    assert report.status == "issues"
    assert report.score <= 40


def test_vfr_and_hdr_are_review_warnings(tmp_path: Path) -> None:
    vfr = evaluate_readiness(_info(tmp_path, r_fps=Fraction(60)), "tiktok")
    assert next(c for c in vfr.checks if c.check_id == "frame_rate").status == "warning"
    assert vfr.status == "review"

    hdr = evaluate_readiness(
        _info(tmp_path, color_primaries="bt2020", color_transfer="smpte2084"),
        "tiktok",
    )
    hdr_check = next(c for c in hdr.checks if c.check_id == "hdr_color")
    assert hdr_check.status == "warning"
    assert "HDR" in hdr_check.detail
    assert hdr.status == "review"


def test_non_aac_audio_and_wrong_sample_rate_warn(tmp_path: Path) -> None:
    report = evaluate_readiness(
        _info(tmp_path, audio_codec="pcm_s16le", audio_sample_rate=44100, audio_channels=1),
        "tiktok",
    )
    audio = next(c for c in report.checks if c.check_id == "audio")
    assert audio.status == "warning"
    assert "AAC" in (audio.recommendation or "")
    assert report.status == "review"


def test_threshold_boundaries_are_inclusive_for_pass(tmp_path: Path) -> None:
    at_limit = evaluate_readiness(_info(tmp_path, bit_rate=20_000_000), "tiktok")
    assert next(c for c in at_limit.checks if c.check_id == "bitrate").status == "pass"
    above_limit = evaluate_readiness(_info(tmp_path, bit_rate=20_000_001), "tiktok")
    assert next(c for c in above_limit.checks if c.check_id == "bitrate").status == "warning"

    for fps in (23, 60):
        report = evaluate_readiness(
            _info(tmp_path, avg_fps=Fraction(fps), r_fps=Fraction(fps)), "tiktok"
        )
        assert next(c for c in report.checks if c.check_id == "frame_rate").status == "pass"
    for fps in (22, 61):
        report = evaluate_readiness(
            _info(tmp_path, avg_fps=Fraction(fps), r_fps=Fraction(fps)), "tiktok"
        )
        assert next(c for c in report.checks if c.check_id == "frame_rate").status == "error"

    at_duration = evaluate_readiness(_info(tmp_path, duration_s=600.0), "tiktok")
    assert next(c for c in at_duration.checks if c.check_id == "duration").status == "pass"
    over_duration = evaluate_readiness(_info(tmp_path, duration_s=600.1), "tiktok")
    assert next(c for c in over_duration.checks if c.check_id == "duration").status == "warning"


def test_unsupported_container_and_codec_are_blockers(tmp_path: Path) -> None:
    info = _info(tmp_path, format_name="matroska,webm", codec="mpeg4")
    report = evaluate_readiness(info, "tiktok")
    checks = {c.check_id: c for c in report.checks}
    assert checks["container"].status == "error"
    assert checks["video_codec"].status == "error"
    assert report.status == "issues"
    assert report.score <= 40


def test_malformed_probe_values_do_not_crash(tmp_path: Path) -> None:
    info = _info(
        tmp_path,
        width=-1920,
        height=0,
        avg_fps=Fraction(-30),
        r_fps=Fraction(0),
        duration_s=-1.0,
        bit_rate=-5,
        audio_sample_rate=0,
        audio_channels=0,
        format_name="unknown",
    )
    report = evaluate_readiness(info, "tiktok")
    assert report.status in ("review", "issues")
    assert 0 <= report.score <= 100
    assert "frame_geometry" in {c.check_id for c in report.unknown_checks}


def test_parse_probe_exposes_color_and_container_fields(tmp_path: Path) -> None:
    path = tmp_path / "probe.mp4"
    info = parse_probe(
        path,
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30/1",
                    "r_frame_rate": "30/1",
                    "duration": "10.0",
                    "time_base": "1/30000",
                    "nb_frames": "300",
                    "bit_rate": "12000000",
                    "color_primaries": "bt2020",
                    "color_transfer": "smpte2084",
                    "color_space": "bt2020nc",
                    "pix_fmt": "yuv420p10le",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                },
            ],
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.0"},
        },
    )
    assert info.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert info.color_primaries == "bt2020"
    assert info.color_transfer == "smpte2084"
    assert info.color_space == "bt2020nc"
    assert info.pix_fmt == "yuv420p10le"


def test_settings_clamp_platform_profile(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    Settings(platform_profile="tiktok").save(target)
    assert Settings.load(target).platform_profile == "tiktok"

    target.write_text('{"platform_profile": "myspace"}', encoding="utf-8")
    assert Settings.load(target).platform_profile == "generic"


def test_new_localization_keys_exist_in_both_languages() -> None:
    keys = {
        "platform_profile_lbl",
        "profile_generic",
        "profile_tiktok",
        "profile_instagram",
        "profile_youtube",
        "readiness_ready",
        "readiness_review",
        "readiness_issues",
        "readiness_unknown",
        "readiness_badge",
        "readiness_badge_ready",
        "readiness_unknown_badge",
        "readiness_disclaimer",
        "readiness_log_title",
        "readiness_log_check",
        "readiness_log_recommend",
        "check_status_pass",
        "check_status_warning",
        "check_status_error",
        "check_status_unknown",
    }
    assert keys <= set(STRINGS["en"])
    assert keys <= set(STRINGS["th"])
    assert set(STRINGS["en"]) == set(STRINGS["th"])


def test_control_panel_profile_selector_updates_setting(
    tk_root: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fps_patcher.ui.control_panel import ControlPanel

    monkeypatch.setattr(Settings, "save_async", lambda self: None)
    settings = Settings(platform_profile="generic")
    changes: list[str] = []
    panel = ControlPanel(
        tk_root,
        settings=settings,
        on_patch=lambda _ts, _strategy: None,
        on_cancel=lambda: None,
        on_profile_change=lambda: changes.append(settings.platform_profile),
    )
    panel.pack()
    try:
        assert panel.profile.get() == t("profile_generic", "en")
        panel._profile_selected(t("profile_tiktok", "en"))
        assert settings.platform_profile == "tiktok"
        assert changes == ["tiktok"]

        panel.set_profile("instagram")
        assert settings.platform_profile == "instagram"
        assert panel.profile.get() == t("profile_instagram", "en")
    finally:
        panel.destroy()


def test_queue_card_readiness_badge_refreshes_on_profile_change(
    tk_root: object, tmp_path: Path
) -> None:
    from unittest.mock import patch

    from fps_patcher.app.controller import AppController
    from fps_patcher.ui.drop_zone import DropZone
    from fps_patcher.ui.input_list import InputList

    settings = Settings(platform_profile="tiktok")
    controller = AppController(settings)
    target = tmp_path / "ready.mp4"
    target.write_bytes(b"x")
    assert controller.items.add([target]).added
    controller.items.set_info(target, _info(tmp_path, bit_rate=30_000_000))

    with patch.object(DropZone, "drop_target_register", return_value=None):
        widget = InputList(tk_root, controller=controller, on_start_patch_selected=lambda: None)
        widget.pack()
        try:
            widget.render()
            item = controller.items.get(target)
            assert item is not None
            row = widget._row_widgets[item.item_id]
            assert row.readiness_badge.cget("text") == "TikTok Review 88%"
            widget._log_readiness(target)
            messages: list[str] = []
            while not controller.events.empty():
                event = controller.events.get_nowait()
                if isinstance(event, LogEvent):
                    messages.append(event.message)
            assert any("READINESS" in message for message in messages)
            assert any("Bitrate" in message for message in messages)

            settings.platform_profile = "generic"
            widget.render()
            assert row.readiness_badge.cget("text") == "Basic Ready 100%"
        finally:
            widget.destroy()
