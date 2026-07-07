# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/rules.py — project rules files.

Instructions in `.tythanrules`, `.cursorrules` (existing Cursor projects
keep working unchanged) or `AGENTS.md` at the workspace root are appended
to the system prompt on every turn. Re-read each turn, so edits apply on
the next message.
"""
from __future__ import annotations

from pathlib import Path

RULES_FILENAMES = (".tythanrules", ".cursorrules", "AGENTS.md")
MAX_RULES_CHARS = 16_000


def load_rules(workspace_root: Path) -> str:
    """Return the first non-empty rules file's content (precedence order),
    truncated to MAX_RULES_CHARS."""
    for name in RULES_FILENAMES:
        fp = workspace_root / name
        try:
            if not fp.is_file():
                continue
            text = fp.read_text("utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > MAX_RULES_CHARS:
            text = text[:MAX_RULES_CHARS] + "\n…(rules truncated)"
        return f"\n\n# Project rules (from {name})\n{text}"
    return ""
