"""v2.0.0 Slice 5: multi-platform export fan-out (settings, controller, CLI)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.cli import EXIT_USAGE, main
from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchError
from fps_patcher.core.models import LogEvent, PatchRequest
from fps_patcher.core.patcher import output_base_for


def _mk(tmp: Path, name: str = "clip.mp4") -> Path:
    path = tmp / name
    path.write_bytes(b"x")
    return path


def _fake_patch(
    tmp_path: Path, captured: list[PatchRequest], *, fail_first: bool = False
) -> Any:
    calls = 0

    def fake(request: PatchRequest, *_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        captured.append(request)
        if fail_first and calls == 1:
            raise PatchError("first target failed")
        return SimpleNamespace(
            output=tmp_path / f"out_{request.platform_profile}.mp4",
            experimental=False,
            after=None,
        )

    return fake


def _finish(ctrl: AppController, timeout: float = 5.0) -> list[object]:
    seen: list[object] = []
    deadline = time.time() + timeout
    while ctrl.busy and time.time() < deadline:
        ctrl.drain(seen.append)
        time.sleep(0.01)
    assert not ctrl.busy
    ctrl.drain(seen.append)
    return seen


def _start(ctrl: AppController, clip: Path) -> list[object]:
    ctrl.items.add([clip])
    ctrl.items.toggle(clip)
    ctrl.start_patch(60000, "direct-atom")
    return _finish(ctrl)


# ---------- settings ----------


def test_settings_export_platforms_clamps_dedupes_and_drops_generic() -> None:
    settings = Settings(
        export_platforms=["tiktok", "bogus", "youtube", "tiktok", "generic"]
    )
    settings._clamp()
    assert settings.export_platforms == ["tiktok", "youtube"]


def test_settings_export_platforms_non_list_becomes_empty() -> None:
    settings = Settings()
    settings.export_platforms = "tiktok"  # type: ignore[assignment]
    settings._clamp()
    assert settings.export_platforms == []


def test_settings_legacy_file_loads_empty_export_platforms(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"last_preset": "60 FPS"}), encoding="utf-8")
    assert Settings.load(path).export_platforms == []


def test_settings_export_platforms_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(export_platforms=["instagram", "youtube"]).save(path)
    assert Settings.load(path).export_platforms == ["instagram", "youtube"]


# ---------- controller fan-out ----------


def test_controller_exports_once_per_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(output_dir=str(tmp_path), export_platforms=["tiktok", "youtube"])
    ctrl = AppController(settings)
    clip = _mk(tmp_path)

    events = _start(ctrl, clip)

    assert [req.platform_profile for req in captured] == ["tiktok", "youtube"]
    assert {output_base_for(req) for req in captured} == {
        tmp_path / "clip_ts60000_tiktok.mp4",
        tmp_path / "clip_ts60000_youtube.mp4",
    }
    item = ctrl.items.get(clip)
    assert item is not None and item.status == "done"
    assert item.output == tmp_path / "out_youtube.mp4"
    messages = [e.message for e in events if isinstance(e, LogEvent)]
    assert any("Output (tiktok)" in message for message in messages)
    assert any("Output (youtube)" in message for message in messages)


def test_controller_item_override_exports_only_that_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(output_dir=str(tmp_path), export_platforms=["tiktok", "youtube"])
    ctrl = AppController(settings)
    clip = _mk(tmp_path)
    ctrl.items.add([clip])
    ctrl.items.toggle(clip)
    ctrl.items.set_override(clip, platform_profile="instagram")

    ctrl.start_patch(60000, "direct-atom")
    _finish(ctrl)

    assert [req.platform_profile for req in captured] == ["instagram"]
    assert captured[0].filename_template == ""


def test_controller_empty_export_platforms_uses_legacy_single_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(output_dir=str(tmp_path), platform_profile="youtube")
    ctrl = AppController(settings)

    _start(ctrl, _mk(tmp_path))

    assert [req.platform_profile for req in captured] == ["youtube"]
    assert captured[0].filename_template == ""


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("", "{name}_ts{timescale}_{platform}"),
        ("{name}_{fps}fps", "{name}_{fps}fps_{platform}"),
        ("{name}_{platform}_{fps}fps", "{name}_{platform}_{fps}fps"),
    ],
)
def test_controller_multi_export_template_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    expected: str,
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch", _fake_patch(tmp_path, captured)
    )
    settings = Settings(
        output_dir=str(tmp_path),
        export_platforms=["tiktok", "youtube"],
        filename_template=template or "{name}_{fps}fps",
        use_filename_template=bool(template),
    )
    ctrl = AppController(settings)

    _start(ctrl, _mk(tmp_path))

    assert [req.filename_template for req in captured] == [expected, expected]
    assert len({output_base_for(req) for req in captured}) == 2


def test_controller_first_target_failure_skips_remaining_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr(
        "fps_patcher.app.controller.patch",
        _fake_patch(tmp_path, captured, fail_first=True),
    )
    settings = Settings(output_dir=str(tmp_path), export_platforms=["tiktok", "youtube"])
    ctrl = AppController(settings)
    clip = _mk(tmp_path)

    _start(ctrl, clip)

    assert [req.platform_profile for req in captured] == ["tiktok"]
    item = ctrl.items.get(clip)
    assert item is not None and item.status == "failed"
    assert item.error is not None and "first target failed" in item.error


# ---------- CLI ----------


def test_cli_platforms_exports_each_platform_with_json_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path)

    code = main(
        [
            "patch",
            str(clip),
            "--strategy",
            "direct-atom",
            "--platforms",
            "tiktok,youtube",
            "--json",
        ],
        Settings(),
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [req.platform_profile for req in captured] == ["tiktok", "youtube"]
    assert [entry["platform"] for entry in payload["files"]] == ["tiktok", "youtube"]
    assert all(entry["ok"] for entry in payload["files"])
    assert captured[0].filename_template == "{name}_ts{timescale}_{platform}"


def test_cli_platforms_appends_platform_to_custom_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path)
    settings = Settings(
        use_filename_template=True, filename_template="{name}_{fps}fps"
    )

    code = main(
        ["patch", str(clip), "--strategy", "direct-atom", "--platforms", "tiktok,youtube"],
        settings,
    )

    assert code == 0
    assert [req.filename_template for req in captured] == [
        "{name}_{fps}fps_{platform}",
        "{name}_{fps}fps_{platform}",
    ]


def test_cli_uses_settings_export_platforms_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path)
    settings = Settings(export_platforms=["tiktok", "youtube"])

    assert main(["patch", str(clip), "--strategy", "direct-atom"], settings) == 0
    assert [req.platform_profile for req in captured] == ["tiktok", "youtube"]


def test_cli_platforms_and_profile_conflict_is_usage_error(tmp_path: Path) -> None:
    clip = _mk(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(
            ["patch", str(clip), "--platforms", "tiktok", "--profile", "youtube"],
            Settings(),
        )

    assert exc.value.code == EXIT_USAGE


@pytest.mark.parametrize("value", ["myspace", "", ",", "tiktok,generic"])
def test_cli_platforms_rejects_unknown_or_empty(
    tmp_path: Path, capsys: Any, value: str
) -> None:
    clip = _mk(tmp_path)

    assert main(["patch", str(clip), "--platforms", value], Settings()) == EXIT_USAGE
    assert "--platforms" in capsys.readouterr().err


def test_cli_single_platform_path_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    captured: list[PatchRequest] = []
    monkeypatch.setattr("fps_patcher.cli.patch", _fake_patch(tmp_path, captured))
    clip = _mk(tmp_path)

    code = main(
        ["patch", str(clip), "--strategy", "direct-atom", "--json"], Settings()
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(captured) == 1
    assert captured[0].platform_profile == "generic"
    assert captured[0].filename_template == ""
    assert "platform" not in payload["files"][0]
