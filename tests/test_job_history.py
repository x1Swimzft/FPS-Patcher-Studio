"""Job history persistence and rollback (no real FFmpeg except one core patch)."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from fps_patcher.app.controller import AppController
from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.job_history import (
    JobRecord,
    load_history,
    record_job,
    undo_job,
)
from fps_patcher.core.models import PatchRequest, PatchResult, VideoInfo
from fps_patcher.core.patcher import output_path_for, patch


def _video(path: Path) -> VideoInfo:
    return VideoInfo(
        path=path,
        codec="h264",
        width=320,
        height=240,
        avg_fps=Fraction(30),
        r_fps=Fraction(30),
        duration_s=2.0,
        timescale=30000,
        nb_frames=60,
        has_audio=False,
        stream_count=1,
    )


def _record(
    history: Path,
    *,
    output: Path,
    backup: Path | None = None,
    timescale: int = 60000,
    strategy: str = "timescale",
    profile: str = "generic",
) -> JobRecord:
    src = output.with_name("source.mp4")
    req = PatchRequest(
        src=src,
        out_dir=output.parent,
        timescale=timescale,
        strategy=strategy,
        platform_profile=profile,
    )
    result = PatchResult(
        src=src,
        output=output,
        before=_video(src),
        after=_video(output),
        elapsed_s=0.1,
        backup_path=backup,
    )
    job = record_job(result, req, history_path=history)
    assert job is not None
    return job


def test_record_and_load_round_trip(tmp_path: Path) -> None:
    history = tmp_path / "job_history.json"
    backup = tmp_path / "one.mp4.bak"
    backup.write_bytes(b"old")
    first = _record(
        history,
        output=tmp_path / "one.mp4",
        backup=backup,
        timescale=90000,
        strategy="direct-atom",
        profile="tiktok",
    )
    second = _record(history, output=tmp_path / "two.mp4")

    jobs = load_history(history_path=history)
    assert [job.job_id for job in jobs] == [second.job_id, first.job_id]
    assert load_history(history_path=history, limit=1) == [jobs[0]]

    saved = jobs[1]
    assert saved.src == str(tmp_path / "source.mp4")
    assert saved.output == str(tmp_path / "one.mp4")
    assert saved.backup == str(backup)
    assert saved.timescale == 90000
    assert saved.strategy == "direct-atom"
    assert saved.platform_profile == "tiktok"
    assert saved.rolled_back is False
    assert datetime.fromisoformat(saved.timestamp).tzinfo is not None


def test_history_keeps_only_newest_200(tmp_path: Path) -> None:
    history = tmp_path / "job_history.json"
    for index in range(201):
        _record(history, output=tmp_path / f"out{index}.mp4")

    jobs = load_history(history_path=history, limit=500)
    assert len(jobs) == 200
    assert jobs[0].output == str(tmp_path / "out200.mp4")
    assert jobs[-1].output == str(tmp_path / "out1.mp4")


def test_concurrent_record_jobs_are_not_lost(tmp_path: Path) -> None:
    import threading

    history = tmp_path / "job_history.json"
    barrier = threading.Barrier(2)
    jobs: list[JobRecord] = []

    def worker(index: int) -> None:
        barrier.wait(timeout=5)
        jobs.append(_record(history, output=tmp_path / f"out{index}.mp4"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(jobs) == 2
    assert {job.job_id for job in jobs} == {
        job.job_id for job in load_history(history_path=history)
    }


def test_malformed_or_missing_history_reads_empty_and_record_recovers(
    tmp_path: Path,
) -> None:
    history = tmp_path / "job_history.json"
    assert load_history(history_path=history) == []

    history.write_text("{not json", encoding="utf-8")
    assert load_history(history_path=history) == []

    history.write_text('{"job_id": "not-a-list"}', encoding="utf-8")
    assert load_history(history_path=history) == []

    job = _record(history, output=tmp_path / "out.mp4")
    assert [record.job_id for record in load_history(history_path=history)] == [job.job_id]


def test_undo_restores_backup_and_marks_rolled_back(tmp_path: Path) -> None:
    history = tmp_path / "job_history.json"
    output = tmp_path / "out.mp4"
    backup = tmp_path / "out.mp4.bak"
    output.write_bytes(b"patched")
    backup.write_bytes(b"original")
    job = _record(history, output=output, backup=backup)

    restored = undo_job(job.job_id, history_path=history)
    assert restored.rolled_back is True
    assert output.read_bytes() == b"original"
    assert not backup.exists()
    assert load_history(history_path=history)[0].rolled_back is True

    with pytest.raises(PatchError, match="already rolled back"):
        undo_job(job.job_id, history_path=history)
    with pytest.raises(PatchError, match="No patch job"):
        undo_job(history_path=history)


def test_undo_without_id_rolls_back_latest_unrolled_job(tmp_path: Path) -> None:
    history = tmp_path / "job_history.json"
    older_out = tmp_path / "older.mp4"
    newer_out = tmp_path / "newer.mp4"
    older_out.write_bytes(b"older patched")
    newer_out.write_bytes(b"newer patched")
    older_bak = tmp_path / "older.mp4.bak"
    newer_bak = tmp_path / "newer.mp4.bak"
    older_bak.write_bytes(b"older original")
    newer_bak.write_bytes(b"newer original")
    _record(history, output=older_out, backup=older_bak)
    newer = _record(history, output=newer_out, backup=newer_bak)

    restored = undo_job(history_path=history)
    assert restored.job_id == newer.job_id
    assert newer_out.read_bytes() == b"newer original"
    assert older_out.read_bytes() == b"older patched"


def test_undo_missing_backup_or_job_raises(tmp_path: Path) -> None:
    history = tmp_path / "job_history.json"
    output = tmp_path / "out.mp4"
    output.write_bytes(b"patched")
    missing_backup = tmp_path / "out.mp4.bak"
    job = _record(history, output=output, backup=missing_backup)

    with pytest.raises(PatchError, match="missing"):
        undo_job(job.job_id, history_path=history)
    assert output.read_bytes() == b"patched"

    with pytest.raises(PatchError, match="Job not found"):
        undo_job("no-such-job", history_path=history)


def test_undo_while_patching_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl = AppController(Settings())
    monkeypatch.setattr(AppController, "busy", property(lambda _self: True))

    with pytest.raises(
        PatchError, match="Cannot roll back while patching is in progress."
    ):
        ctrl.undo_job()


def test_patch_records_backup_path_for_overwritten_output(
    clip30: Path,
    ff: FFmpegPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_record(
        result: PatchResult, req: PatchRequest, *, history_path: Path | None = None
    ) -> None:
        captured["result"] = result
        captured["req"] = req

    monkeypatch.setattr("fps_patcher.core.job_history.record_job", fake_record)
    req = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        strategy="direct-atom",
        overwrite=True,
    )
    final = output_path_for(req)
    final.write_bytes(b"previous output")

    result = patch(req, ff, lambda _event: None)

    assert result.backup_path is not None
    assert result.backup_path.is_file()
    assert result.backup_path.read_bytes() == b"previous output"
    assert captured["result"].backup_path == result.backup_path
    assert captured["req"] is req
