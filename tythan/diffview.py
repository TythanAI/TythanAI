# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""tythan/diffview.py — colorized unified diffs for the approval prompt."""
from __future__ import annotations

import difflib

from tythan import ui

MAX_DIFF_LINES = 400


def render_diff(old: str | None, new: str, path: str) -> str:
    if old is None:
        header = ui.bold(f"── new file: {path} ")
        body_lines = [ui.green("+ " + line) for line in new.splitlines()]
    else:
        header = ui.bold(f"── edit: {path} ")
        body_lines = []
        diff = difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        )
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                body_lines.append(ui.dim(line))
            elif line.startswith("@@"):
                body_lines.append(ui.cyan(line))
            elif line.startswith("+"):
                body_lines.append(ui.green(line))
            elif line.startswith("-"):
                body_lines.append(ui.red(line))
            else:
                body_lines.append(line)
    if len(body_lines) > MAX_DIFF_LINES:
        omitted = len(body_lines) - MAX_DIFF_LINES
        body_lines = body_lines[:MAX_DIFF_LINES] + [ui.dim(f"… ({omitted} more lines)")]
    return header + "\n" + "\n".join(body_lines) if body_lines else header + "\n(no changes)"
