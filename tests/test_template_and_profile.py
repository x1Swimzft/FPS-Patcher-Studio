"""v2.0.0 Slice 1: filename template routing and per-item platform profile."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.app import quick_patch
from fps_patcher.app.controller import AppController
from fps_patcher.app.queue_model import InputQueue
from fps_patcher.app.watcher import FolderWatcher
from fps_patcher.cli import main
from fps_patcher.config import Settings, render_filename_template
from fps_patcher.core.models import PatchRequest
from fps_patcher.core.patcher import output_base_for


def _mk(tmp: Path, name: str) -> Path:
    path = tmp / name
    path.write_bytes(b"x")
    return path


def _req(**overrides: Any) -> PatchRequest:
    values: dict[str, Any] = {
        "src": Path("clip.mp4"),
        "out_dir": Path("out"),
        "timescale": 60000,
        "strategy": "bxd-mobile",
    }
    values.update(overrides)
    return PatchRequest(**values)


# ---------- template rendering ----------


def test_render_template_platform_and_strategy_tokens() -> None:
    rendered = render_filename_template(
        "{name}_{platform}_{strategy}_{fps}fps",
        "clip",
        60,
        platform="tiktok",
        strategy="bxd-mobile",
    )
    assert rendered == "clip_tiktok_bxd-mobile_60fps"


def test_render_template_sanitizes_rendered_tokens() -> None:
    rendered = render_filename_template(
        "{name}_{platform}_{fps}fps", "clip", 60, platform="tik/tok:eu"
    )
    assert rendered == "clip_tik_tok_eu_60fps"


def test_render_template_unknown_token_still_falls_back() -> None:
    assert render_filename_template("{name}_{bogus}_{fps}", "clip", 60) == "clip_60fps"


# ---------- output naming ----------


def test_output_base_legacy_when_template_empty() -> None:
    base = output_base_for(_req())
    assert base == Path("out") / "clip_ts60000.mp4"


def test_output_base_uses_rendered_template() -> None:
    base = output_base_for(
        _req(
            filename_template="{name}_{platform}_{fps}fps",
            platform_profile="tiktok",
        )
    )
    assert base == Path("out") / "clip_tiktok_60fps.mp4"


def test_output_base_mov_with_bxd_gets_mp4_extension() -> None:
    base = output_base_for(
        _req(
            src=Path("clip.mov"),
            filename_template="{name}_{fps}fps",
        )
    )
    assert base == Path("out") / "clip_60fps.mp4"


# ---------- settings ----------


def test_use_filename_template_defaults_off_and_survives_clamp(tmp_path: Path) -> None:
    assert Settings().use_filename_template is False

    old = tmp_path / "settings.json"
    old.write_text('{"filename_template": "{name}_{fps}fps"}', encoding="utf-8")
    assert Settings.load(old).use_filename_template is False

    enabled = Settings(use_filename_template=True, filename_template="")
    enabled._clamp()
    assert enabled.use_filename_template is True
    assert enabled.filename_template == "{name}_{fps}fps"


# ---------- queue profile round-trip ----------


def test_queue_platform_profile_roundtrip(tmp_path: Path) -> None:
    clip = _mk(tmp_path, "clip.mp4")
    queue = InputQueue()
    queue.add([clip])
    queue.set_override(clip, platform_profile="tiktok")

    saved = tmp_path / "queue.json"
    queue.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))[0]["platform_profile"] == "tiktok"

    loaded = InputQueue.load(saved)
    item = loaded.get(clip)
    assert item is not None
    assert item.platform_profile == "tiktok"


def test_queue_old_entry_without_profile_loads_none(tmp_path: Path) -> None:
    clip = _mk(tmp_path, "clip.mp4")
    saved = tmp_path / "queue.json"
    saved.write_text(json.dumps([{"path": str(clip)}]), encoding="utf-8")

    item = InputQueue.load(saved).get(clip)
    assert item is not None
    assert item.platform_profile is None


def test_set_override_profile_does_not_touch_timescale_or_strategy(tmp_path: Path) -> None:
    clip = _mk(tmp_path, "clip.mp4")
    queue = InputQueue()
    queue.add([clip])
    queue.set_override(clip, timescale=90000, strategy="direct-atom")

    queue.set_override(clip, platform_profile="youtube")
    item = queue.get(clip)
    assert item is not None
    assert item.timescale == 90000
    assert item.strategy == "direct-atom"
    assert item.platform_profile == "youtube"

    queue.set_override(clip, platform_profile=None)
    assert item.platform_profile is None
    assert item.timescale == 90000
    assert item.strategy == "direct-atom"

    # An omitted field keeps its value; explicit None clears only that field.
    queue.set_override(clip, timescale=120000)
    assert item.timescale == 120000
    assert item.strategy == "direct-atom"
    queue.set_override(clip, timescale=None)
    assert item.timescale is None
    assert item.strategy == "direct-atom"


# ---------- controller requests ----------


def _wait_idle(ctrl: AppController, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while ctrl.busy and time.time() < deadline:
        ctrl.drain(lambda _event: None)
        time.sleep(0.01)
    assert not ctrl.busy
    ctrl.drain(lambda _event: None)


def _fake_patch(tmp_path: Path, captured: list[PatchRequest]) -> Any:
    def fake(request: PatchRequest, *_args: object, **_kwargs: object) -> SimpleNamespace:
        captured.append(request)
        return SimpleNamespace(
            output=tmp_path / "out.mp4", experimental=False, after=None
        )

    return fake


def test_controller_uses_item_profile_and_enabled_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(
        output_dir=str(tmp_path),
        platform_profile="youtube",
        filename_template="{name}_{platform}_{fps}fps",
        use_filename_template=True,
    )
    ctrl = AppController(settings)
    clip = _mk(tmp_path, "clip.mp4")
    ctrl.items.add([clip])
    ctrl.items.toggle(clip)
    ctrl.items.set_override(clip, platform_profile="tiktok")

    ctrl.start_patch(60000, "direct-atom")
    _wait_idle(ctrl)

    assert len(captured) == 1
    assert captured[0].platform_profile == "tiktok"
    assert captured[0].filename_template == "{name}_{platform}_{fps}fps"


def test_controller_global_profile_and_legacy_name_when_template_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(
        output_dir=str(tmp_path),
        platform_profile="instagram",
        filename_template="{name}_{fps}fps",
        use_filename_template=False,
    )
    ctrl = AppController(settings)
    clip = _mk(tmp_path, "clip.mp4")
    ctrl.items.add([clip])
    ctrl.items.toggle(clip)

    ctrl.start_patch(60000, "direct-atom")
    _wait_idle(ctrl)

    assert len(captured) == 1
    assert captured[0].platform_profile == "instagram"
    assert captured[0].filename_template == ""


# ---------- quick patch ----------


def test_quick_patch_passes_template_and_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.quick_patch.patch", _fake_patch(tmp_path, captured)
    )
    monkeypatch.setattr("fps_patcher.app.quick_patch._ffmpeg", lambda _settings: None)
    clip = _mk(tmp_path, "clip.mp4")
    settings = Settings(
        filename_template="{name}_{platform}_{fps}fps",
        use_filename_template=True,
        platform_profile="tiktok",
    )

    assert quick_patch.run(clip, settings, show_toast=False) == 0
    assert captured[0].filename_template == "{name}_{platform}_{fps}fps"
    assert captured[0].platform_profile == "tiktok"


# ---------- CLI ----------


def test_cli_patch_accepts_template_and_profile_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path, "clip.mp4")

    code = main(
        [
            "patch",
            str(clip),
            "--strategy",
            "direct-atom",
            "--template",
            "{name}_{strategy}_{fps}fps",
            "--profile",
            "tiktok",
        ],
        Settings(use_filename_template=False),
    )

    assert code == 0
    assert captured[0].filename_template == "{name}_{strategy}_{fps}fps"
    assert captured[0].platform_profile == "tiktok"


def test_cli_patch_defaults_follow_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path, "clip.mp4")
    settings = Settings(
        filename_template="{name}_{platform}_{fps}fps",
        use_filename_template=True,
        platform_profile="youtube",
    )

    assert main(["patch", str(clip), "--strategy", "direct-atom"], settings) == 0
    assert captured[0].filename_template == "{name}_{platform}_{fps}fps"
    assert captured[0].platform_profile == "youtube"

    settings.use_filename_template = False
    assert main(["patch", str(clip), "--strategy", "direct-atom"], settings) == 0
    assert captured[1].filename_template == ""


def test_cli_patch_rejects_unknown_profile(tmp_path: Path) -> None:
    clip = _mk(tmp_path, "clip.mp4")
    with pytest.raises(SystemExit) as exc:
        main(["patch", str(clip), "--profile", "myspace"], Settings())
    assert exc.value.code == 2


# ---------- watcher ----------


@pytest.mark.parametrize(
    "name",
    [
        "clip_ts60000.mp4",
        "clip_60fps.mp4",
        "clip_tiktok_60fps.mp4",
        "clip_60fps (1).mp4",
    ],
)
def test_watcher_ignores_own_output_patterns(name: str) -> None:
    assert FolderWatcher.is_own_output(Path(name))


def test_watcher_plain_clip_is_not_own_output() -> None:
    assert not FolderWatcher.is_own_output(Path("clip.mp4"))


def test_record_own_output_marks_arbitrary_name(tmp_path: Path) -> None:
    output = _mk(tmp_path, "client export final.mp4")
    assert not FolderWatcher.is_own_output(output)

    FolderWatcher.record_own_output(output)
    assert FolderWatcher.is_own_output(output)

    seen: list[Path] = []
    watcher = FolderWatcher(tmp_path, seen.append, settle_scans=1, min_age_s=0.0)
    watcher.scan(now=0.0)
    watcher.scan(now=1.0)
    assert seen == []
