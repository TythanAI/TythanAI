# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/checkpoints.py — file-level undo for agent-authored changes.

Before every approved write the previous file state is recorded; one
checkpoint groups every file changed in a single user turn, so /undo
reverts the whole turn. Files that are too large or not valid UTF-8 are
skipped (recorded as such) rather than checkpointed, so undo can never
"restore" a corrupted copy.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHECKPOINT_FILE_BYTES = 5 * 1024 * 1024
MAX_CHECKPOINTS = 50


@dataclass
class FileSnapshot:
    path: Path
    existed: bool
    content: str | None      # None when skipped or file didn't exist


@dataclass
class Checkpoint:
    label: str
    created_at: float = field(default_factory=time.time)
    snapshots: dict[Path, FileSnapshot] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


class CheckpointStore:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._stack: list[Checkpoint] = []
        self._current: Checkpoint | None = None

    # ── Turn lifecycle ───────────────────────────────────────────────────

    def begin_turn(self, label: str) -> None:
        if self.enabled:
            self._current = Checkpoint(label=label)

    def commit_turn(self) -> None:
        """Keep the turn's checkpoint if it recorded anything."""
        cp = self._current
        self._current = None
        if cp and (cp.snapshots or cp.skipped):
            self._stack.append(cp)
            del self._stack[:-MAX_CHECKPOINTS]

    # ── Recording ────────────────────────────────────────────────────────

    def record(self, path: Path) -> None:
        """Snapshot a file's pre-write state. Call before the write."""
        cp = self._current
        if cp is None or path in cp.snapshots:
            return
        if not path.exists():
            cp.snapshots[path] = FileSnapshot(path, existed=False, content=None)
            return
        try:
            if not path.is_file() or path.is_symlink():
                cp.skipped.append(f"{path} (not a regular file)")
                return
            if path.stat().st_size > MAX_CHECKPOINT_FILE_BYTES:
                cp.skipped.append(f"{path} (over {MAX_CHECKPOINT_FILE_BYTES // (1024 * 1024)}MB)")
                return
            content = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            cp.skipped.append(f"{path} (not valid UTF-8)")
            return
        except OSError as exc:
            cp.skipped.append(f"{path} ({exc})")
            return
        cp.snapshots[path] = FileSnapshot(path, existed=True, content=content)

    # ── Undo ─────────────────────────────────────────────────────────────

    def undo_last(self) -> tuple[list[str], list[str]]:
        """Revert the most recent checkpoint. Returns (restored, problems)."""
        if not self._stack:
            return [], ["nothing to undo"]
        cp = self._stack.pop()
        restored: list[str] = []
        problems: list[str] = list(cp.skipped)
        for snap in cp.snapshots.values():
            try:
                if not snap.existed:
                    if snap.path.exists():
                        snap.path.unlink()
                        restored.append(f"{snap.path} (deleted — didn't exist before)")
                    continue
                # Refuse to follow a symlink introduced after checkpointing.
                if snap.path.exists() and snap.path.is_symlink():
                    problems.append(f"{snap.path} (became a symlink; not restored)")
                    continue
                snap.path.parent.mkdir(parents=True, exist_ok=True)
                snap.path.write_text(snap.content or "", "utf-8")
                restored.append(str(snap.path))
            except OSError as exc:
                problems.append(f"{snap.path} ({exc})")
        return restored, problems

    def list(self) -> list[str]:
        out = []
        for i, cp in enumerate(reversed(self._stack), 1):
            when = time.strftime("%H:%M:%S", time.localtime(cp.created_at))
            out.append(f"{i}. [{when}] {cp.label} — {len(cp.snapshots)} file(s)"
                       + (f", {len(cp.skipped)} skipped" if cp.skipped else ""))
        return out
