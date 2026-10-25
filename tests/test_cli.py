"""Headless CLI (roadmap 4.2): no Qt, clear exit codes, JSON on stdout."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fps_patcher.cli import main
from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchCancelledError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths


def _settings(ff: FFmpegPaths, output: Path) -> Settings:
    return Settings(ffmpeg_dir=str(Path(ff.ffmpeg).parent), output_dir=str(output))


def test_cli_import_graph_has_no_qt() -> None:
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'PySide6', 'shiboken6', 'tkinter', 'customtkinter'}:\n"
        "            raise ImportError('blocked ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "from fps_patcher.cli import main\n"
        "from fps_patcher.__main__ import main as entry\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


def test_cli_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_rejects_bad_preset_and_profile() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["patch", "clip.mp4", "--preset", "30"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["score", "clip.mp4", "--profile", "myspace"])
    assert exc.value.code == 2


def test_cli_rejects_unsupported_file_type(
    ff: FFmpegPaths, tmp_path: Path, capsys: Any
) -> None:
    png = tmp_path / "still.png"
    png.write_bytes(b"x")
    assert main(["probe", str(png)], _settings(ff, tmp_path)) == 2
    assert "unsupported file type" in capsys.readouterr().err


def test_cli_probe_json(clip30: Path, ff: FFmpegPaths, tmp_path: Path, capsys: Any) -> None:
    code = main(["probe", str(clip30), "--json"], _settings(ff, tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "probe"
    assert payload["file"]["codec"] == "h264"
    assert payload["file"]["width"] == 320
    assert payload["file"]["fps"] == pytest.approx(30, abs=0.2)
    assert payload["file"]["timescale"] > 0


def test_cli_score_json(clip30: Path, ff: FFmpegPaths, tmp_path: Path, capsys: Any) -> None:
    code = main(
        ["score", str(clip30), "--profile", "tiktok", "--json"], _settings(ff, tmp_path)
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["command"] == "score"
    assert payload["profile"] == "tiktok"
    assert 0 <= payload["score"] <= 100
    assert payload["status"] in {"ready", "review", "issues", "unknown"}
    assert payload["checks"] and {"id", "status", "detail"} <= set(payload["checks"][0])


def test_cli_patch_success_json(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, capsys: Any
) -> None:
    out_dir = tmp_path / "out"
    code = main(
        [
            "patch",
            str(clip30),
            "--preset",
            "60",
            "--output",
            str(out_dir),
            "--tag-bt709",
            "--json",
        ],
        _settings(ff, out_dir),
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "patch"
    assert payload["cancelled"] is False
    entry = payload["files"][0]
    assert entry["ok"] is True
    assert entry["input"] == str(clip30)
    assert Path(entry["output"]).is_file()


def test_cli_batch_with_one_failing_file(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, capsys: Any
) -> None:
    missing = tmp_path / "missing.mp4"
    out_dir = tmp_path / "out"
    code = main(
        ["patch", str(clip30), str(missing), "--output", str(out_dir), "--json"],
        _settings(ff, out_dir),
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert [entry["ok"] for entry in payload["files"]] == [True, False]
    assert payload["files"][1]["error"]


def test_cli_cancel_returns_130(
    ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    import signal

    def cancelled(
        _request: object, _ffmpeg: object, _emit: object, cancel: Any = None
    ) -> None:
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)  # what Ctrl+C does inside a patch
        assert cancel is not None and cancel.is_set()
        raise PatchCancelledError("Patch cancelled by user.")

    monkeypatch.setattr("fps_patcher.cli.patch", cancelled)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    code = main(["patch", str(clip), "--json"], _settings(ff, tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert code == 130
    assert payload["cancelled"] is True
    assert payload["files"][0]["error"] == "cancelled"


def test_cli_patch_maps_options_to_request(
    ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_patch(request: Any, *_args: object, **_kwargs: object) -> SimpleNamespace:
        captured["request"] = request
        return SimpleNamespace(output=tmp_path / "out.mp4")

    monkeypatch.setattr("fps_patcher.cli.patch", fake_patch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    code = main(
        [
            "patch",
            str(clip),
            "--timescale",
            "90000",
            "--strategy",
            "bxd-mobile",
            "--normalize-audio",
            "--cap-bitrate",
            "--scrub-metadata",
            "--overwrite",
        ],
        _settings(ff, tmp_path),
    )
    request = captured["request"]
    assert code == 0
    assert request.timescale == 90000
    assert request.strategy == "bxd-mobile"
    assert request.auto_normalize_audio is True
    assert request.auto_cap_bitrate is True
    assert request.fix_color_tag is False
    assert request.scrub_metadata is True
    assert request.overwrite is True
    assert request.auto_rename is False
