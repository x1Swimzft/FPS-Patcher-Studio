from __future__ import annotations

from pathlib import Path

from fps_patcher.ui.log_console import LogConsole


def test_log_console_set_context_files(tmp_path: Path) -> None:
    # Test that set_context_files exists on LogConsole and works correctly
    target = tmp_path / "target.mp4"
    source = tmp_path / "source.mp4"

    # We can test the method directly on a dummy instance or mock
    class DummyConsole:
        def __init__(self) -> None:
            self.last_target_file: Path | None = None
            self.last_source_file: Path | None = None

    # Verify the method is bound to LogConsole
    assert hasattr(LogConsole, "set_context_files")

    dummy = DummyConsole()
    LogConsole.set_context_files(dummy, target=target, source=source)  # type: ignore[arg-type]
    assert dummy.last_target_file == target
    assert dummy.last_source_file == source
