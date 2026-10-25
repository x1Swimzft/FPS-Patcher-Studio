"""Forensic dialog parity: actions, export artifacts and repair via the bridge."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt import forensic_dialog as fd  # noqa: E402
from fps_patcher.ui_qt.bridge import ControllerBridge  # noqa: E402
from fps_patcher.ui_qt.forensic_dialog import ForensicDialog  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


class _RepairController:
    busy = False

    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path | None, threading.Thread]] = []

    def repair_file_for_mobile(self, src: Path, out: Path | None = None) -> Path | None:
        self.calls.append((src, out, threading.current_thread()))
        if out is not None:
            out.write_bytes(b"repaired")
        return out

    def drain(self, handler: Any, limit: int = 500) -> None:  # pragma: no cover
        return None


def _dialog(
    qtbot: Any, tmp_path: Path, *, target: Path | None = None, bridge: Any = None
) -> ForensicDialog:
    settings = Settings(reduce_motion=True)
    dialog = ForensicDialog(
        settings,
        ThemeManager(settings),
        preselected_path=target,
        bridge=bridge,
    )
    qtbot.addWidget(dialog)
    return dialog


def _fake_diff(source: Path, target: Path) -> SimpleNamespace:
    return SimpleNamespace(
        original_path=str(source),
        patched_path=str(target),
        file_size_changed=False,
        size_difference=0,
        moov_changed=True,
        mdat_changed=False,
        video_payload_changed=False,
        audio_payload_changed=False,
        changed_atoms=["moov/mvhd"],
        byte_diffs=[],
        semantic_diffs=[],
        bxd_classification={"CHANGED": ["moov/mvhd"]},
        hypothesis=["container only"],
        audio_ghost_samples=0,
        mdat_match=True,
        video_payload_match=True,
        audio_payload_match=True,
        structure_match=True,
    )


def _make_ready(dialog: ForensicDialog, diff: Any, target: Path) -> None:
    dialog._diff = diff
    dialog._analysis_inputs = (None, target)
    dialog._refresh_actions()


def test_dialog_constructs_actions_and_preselected_path(
    qtbot: Any, tmp_path: Path
) -> None:
    target = tmp_path / "patched.mp4"
    target.write_bytes(b"fake mp4")
    dialog = _dialog(qtbot, tmp_path, target=target)

    assert dialog.patched_edit.text() == str(target)
    buttons = {
        t("forensic_repair", dialog.settings.language): dialog.repair_button,
        t("forensic_export_json", dialog.settings.language): dialog.export_json_button,
        t("forensic_export_report", dialog.settings.language): dialog.export_report_button,
        t("forensic_diagnostic_log", dialog.settings.language): dialog.diagnostic_button,
    }
    for label, button in buttons.items():
        assert button.text() == label
        assert button.accessibleName() == label
        assert button.toolTip() == label
        assert button.minimumHeight() >= 26
        assert not button.isEnabled()
    assert dialog.analyze_button.isEnabled()


def test_export_json_calls_core_artifacts_writer(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    source = tmp_path / "orig.mp4"
    target = tmp_path / "patched.mp4"
    source.write_bytes(b"a")
    target.write_bytes(b"b")
    dialog = _dialog(qtbot, tmp_path, target=target)
    diff = _fake_diff(source, target)
    _make_ready(dialog, diff, target)

    out_dir = tmp_path / "artifacts"
    calls: list[tuple[Any, Path]] = []

    def fake_export(result: Any, directory: Path) -> tuple[Path, Path, Path]:
        calls.append((result, directory))
        directory.mkdir(parents=True, exist_ok=True)
        paths = tuple(directory / name for name in ("before.json", "after.json", "diff.json"))
        for path in paths:
            path.write_text("{}", encoding="utf-8")
        return paths  # type: ignore[return-value]

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out_dir))
    )
    monkeypatch.setattr(fd, "export_diff_artifacts", fake_export)
    dialog.export_json_button.click()

    assert calls == [(diff, out_dir)]
    assert (out_dir / "before.json").is_file()
    assert (out_dir / "diff.json").is_file()
    assert dialog.status_label.text() == t(
        "forensic_export_done", dialog.settings.language
    ).format(path=out_dir)


def test_export_report_writes_markdown_report(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    source = tmp_path / "orig.mp4"
    target = tmp_path / "patched.mp4"
    source.write_bytes(b"a")
    target.write_bytes(b"b")
    dialog = _dialog(qtbot, tmp_path, target=target)
    _make_ready(dialog, _fake_diff(source, target), target)

    report = tmp_path / "report.md"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(report), "Markdown (*.md)")),
    )
    dialog.export_report_button.click()

    text = report.read_text(encoding="utf-8")
    assert "MP4 Forensic Report" in text
    assert "moov/mvhd" in text
    assert dialog.status_label.text() == t(
        "forensic_export_done", dialog.settings.language
    ).format(path=report)


def test_repair_runs_through_bridge_and_updates_status(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    target = tmp_path / "patched.mp4"
    target.write_bytes(b"pc-only")
    output = tmp_path / "patched_mobile_repaired.mp4"
    controller = _RepairController()
    bridge = ControllerBridge(controller)  # type: ignore[arg-type]
    bridge.stop()
    dialog = _dialog(qtbot, tmp_path, target=target, bridge=bridge)
    _make_ready(dialog, _fake_diff(tmp_path / "orig.mp4", target), target)

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "Videos (*.mp4)")),
    )
    try:
        with qtbot.waitSignal(bridge.forensic_finished, timeout=2000):
            dialog.repair_button.click()
        qtbot.waitUntil(lambda: not dialog._busy, timeout=2000)
    finally:
        bridge.stop()

    assert len(controller.calls) == 1
    called_source, called_output, worker_thread = controller.calls[0]
    assert called_source == target
    assert called_output == output
    assert worker_thread is not threading.main_thread()
    assert output.is_file()
    assert dialog.patched_edit.text() == str(output)
    assert dialog.status_label.text() == t(
        "forensic_repair_done", dialog.settings.language
    ).format(path=output)


def test_diagnostic_log_uses_auto_save_and_mask_setting(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    target = tmp_path / "patched.mp4"
    target.write_bytes(b"pc-only")
    settings = Settings(reduce_motion=True, mask_diagnostic_paths=False)
    bridge = ControllerBridge(_RepairController())  # type: ignore[arg-type]
    bridge.stop()
    dialog = ForensicDialog(
        settings, ThemeManager(settings), preselected_path=target, bridge=bridge
    )
    qtbot.addWidget(dialog)
    _make_ready(dialog, _fake_diff(tmp_path / "orig.mp4", target), target)
    dialog._console_lines = ["analysis line"]
    log_path = tmp_path / "auto_patch.log"
    calls: list[dict[str, Any]] = []

    def fake_auto_save(**kwargs: Any) -> Path:
        calls.append(kwargs)
        log_path.write_text("log", encoding="utf-8")
        return log_path

    monkeypatch.setattr(
        "fps_patcher.ui_qt.bridge.auto_save_diagnostic_log", fake_auto_save
    )
    try:
        with qtbot.waitSignal(bridge.forensic_finished, timeout=2000):
            dialog.diagnostic_button.click()
        qtbot.waitUntil(lambda: not dialog._busy, timeout=2000)
    finally:
        bridge.stop()

    assert calls == [
        {
            "target_file": target,
            "source_file": None,
            "console_lines": ["analysis line"],
            "mask_paths": False,
        }
    ]
    assert dialog.status_label.text() == t(
        "forensic_export_done", dialog.settings.language
    ).format(path=log_path)


def test_action_without_analysis_reports_need_analysis(qtbot: Any, tmp_path: Path) -> None:
    target = tmp_path / "patched.mp4"
    target.write_bytes(b"pc-only")
    dialog = _dialog(qtbot, tmp_path, target=target)

    dialog._repair()

    assert dialog.status_label.text() == t(
        "forensic_need_analysis", dialog.settings.language
    )
    assert QApplication.instance() is not None
