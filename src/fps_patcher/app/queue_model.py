"""Pure-Python input queue model (no Tk). UI rows bind to ``QueueItem``.

Rules: append never replaces; duplicates (resolved path) are ignored;
selection and per-item overrides live here, so UI stays dumb.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from ..core.models import SUPPORTED_EXTENSIONS, VideoInfo

ItemStatus = Literal["pending", "probing", "ready", "patching", "done", "failed", "skipped"]


def _id_for_resolved(resolved: Path) -> str:
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    return f"{digest[:3]}_{digest[3:9]}"


def short_id(path: Path) -> str:
    """Stable short row id, e.g. ``7e6_d657f0`` (hash of resolved path)."""
    return _id_for_resolved(path.resolve())


@dataclass
class QueueItem:
    path: Path
    status: ItemStatus = "pending"
    info: VideoInfo | None = None
    error: str | None = None
    selected: bool = False
    output: Path | None = None
    # per-item overrides; None = use global setting
    timescale: int | None = None
    strategy: str | None = None
    progress: float = 0.0
    _resolved: Path | None = field(default=None, repr=False)
    item_id: str = field(init=False)
    resolved: Path = field(init=False)

    def __post_init__(self) -> None:
        # add() already resolved the path; only resolve here for direct construction.
        self.resolved = self._resolved if self._resolved is not None else self.path.resolve()
        self.item_id = _id_for_resolved(self.resolved)


@dataclass
class AddResult:
    added: list[Path] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    rejected: list[tuple[Path, str]] = field(default_factory=list)


class InputQueue:
    def __init__(self) -> None:
        self._items: list[QueueItem] = []
        self.migrated_overrides: list[tuple[str, str, str]] = []


    # ---------- read ----------
    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[QueueItem]:
        return list(self._items)

    def paths(self) -> list[Path]:
        return [i.path for i in self._items]

    def selected(self) -> list[QueueItem]:
        return [i for i in self._items if i.selected]

    def get(self, path: Path) -> QueueItem | None:
        key = path.resolve()
        return next((i for i in self._items if i.resolved == key), None)

    # ---------- add / remove ----------
    def add(self, paths: list[Path]) -> AddResult:
        res = AddResult()
        known = {i.resolved for i in self._items}
        for p in paths:
            if not p.is_file():
                res.rejected.append((p, "file not found"))
            elif p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                res.rejected.append((p, f"unsupported type '{p.suffix}'"))
            else:
                resolved = p.resolve()
                if resolved in known:
                    res.duplicates.append(p)
                else:
                    known.add(resolved)
                    self._items.append(QueueItem(path=p, _resolved=resolved))
                    res.added.append(p)
        return res

    def remove_selected(self, locked_path: Path | None = None) -> int:
        before = len(self._items)
        locked_res = locked_path.resolve() if locked_path else None
        self._items = [
            i for i in self._items
            if not i.selected or (locked_res is not None and i.path.resolve() == locked_res)
        ]
        return before - len(self._items)

    def remove(self, path: Path, locked_path: Path | None = None) -> bool:
        if locked_path is not None and path.resolve() == locked_path.resolve():
            return False
        item = self.get(path)
        if item is None:
            return False
        self._items.remove(item)
        return True

    def clear(self, locked_path: Path | None = None) -> None:
        if locked_path is not None:
            locked_res = locked_path.resolve()
            self._items = [i for i in self._items if i.path.resolve() == locked_res]
        else:
            self._items.clear()

    def move(self, path: Path, new_index: int) -> None:
        item = self.get(path)
        if item is None:
            return
        self._items.remove(item)
        self._items.insert(max(0, min(new_index, len(self._items))), item)

    # ---------- selection ----------
    def select_all(self, value: bool = True) -> None:
        for i in self._items:
            i.selected = value

    def toggle(self, path: Path) -> None:
        item = self.get(path)
        if item is not None:
            item.selected = not item.selected

    # ---------- state updates ----------
    def set_info(self, path: Path, info: VideoInfo | None, error: str | None = None) -> None:
        item = self.get(path)
        if item is None:
            return
        item.info = info
        # A late probe result must not resurrect an item that already finished.
        if item.status in ("pending", "probing", "ready"):
            item.error = error
            item.status = "ready" if info is not None else "failed"

    def set_status(
        self,
        path: Path,
        status: ItemStatus,
        *,
        error: str | None = None,
        output: Path | None = None,
    ) -> None:
        item = self.get(path)
        if item is None:
            return
        item.status = status
        item.error = error
        if output is not None:
            item.output = output

    def reset_failed(self) -> int:
        n = 0
        for i in self._items:
            if i.status in ("failed", "skipped"):
                i.status = "ready" if i.info is not None else "pending"
                i.error = None
                n += 1
        return n

    def set_override(
        self, path: Path, *, timescale: int | None = None, strategy: str | None = None
    ) -> None:
        item = self.get(path)
        if item is not None:
            item.timescale = timescale
            item.strategy = strategy

    def reset_for_run(self, paths: list[Path]) -> None:
        """Reset item status, error, progress, and output before patching."""
        path_set = {p.resolve() for p in paths}
        for item in self._items:
            if item.path.resolve() in path_set:
                item.status = "ready" if item.info is not None else "pending"
                item.error = None
                item.progress = 0.0
                item.output = None

    def snapshot_for_run(self, only_selected: bool) -> list[QueueItem]:
        """Items to patch. Selected-only if flag set; re-patches done items when requested."""
        if only_selected:
            return [replace(i) for i in self.selected()]
        not_done = [i for i in self._items if i.status != "done"]
        pool = not_done if not_done else self._items
        return [replace(i) for i in pool]

    # ---------- persistence ----------
    def to_dict_list(self) -> list[dict[str, Any]]:
        """Serialize queue items (paths, overrides, selection) for saving."""
        data = []
        for i in self._items:
            data.append({
                "path": str(i.path),
                "selected": i.selected,
                "timescale": i.timescale,
                "strategy": i.strategy,
            })
        return data

    def save(self, target_path: Path) -> None:
        """Write queue state to JSON file."""
        import json

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(self.to_dict_list(), indent=2), encoding="utf-8")

    def migrate_legacy_overrides(self) -> list[tuple[str, str, str]]:
        """Migrate any legacy per-item strategy overrides to UI_PRESETS keys."""
        from ..core.strategies import migrate_strategy_name

        migrated: list[tuple[str, str, str]] = []
        for item in self._items:
            if isinstance(item.strategy, str) and item.strategy:
                new_s, mig_from = migrate_strategy_name(item.strategy)
                if mig_from is not None:
                    migrated.append((item.path.name, mig_from, new_s))
                    item.strategy = new_s
        self.migrated_overrides.extend(migrated)
        return migrated

    @classmethod
    def load(cls, target_path: Path, *, migrate_legacy: bool = False) -> InputQueue:
        """Load queue from JSON file; auto-prunes missing files."""
        import json

        queue = cls()
        if not target_path.exists():
            return queue

        try:
            raw = json.loads(target_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return queue
        except Exception:
            return queue

        for entry in raw:
            if not isinstance(entry, dict) or "path" not in entry:
                continue
            p = Path(entry["path"])
            if not p.is_file():
                continue
            queue.add([p])
            if entry.get("selected") is not None:
                item = queue.get(p)
                if item:
                    item.selected = bool(entry.get("selected"))
            raw_strat = entry.get("strategy")
            eff_strat = raw_strat if isinstance(raw_strat, str) and raw_strat else None
            if entry.get("timescale") is not None or eff_strat is not None:
                queue.set_override(
                    p,
                    timescale=entry.get("timescale"),
                    strategy=eff_strat,
                )
        if migrate_legacy:
            queue.migrate_legacy_overrides()
        return queue
