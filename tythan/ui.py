# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""tythan/ui.py — ANSI terminal helpers shared by the CLI."""
from __future__ import annotations

import os
import sys

_NO_COLOR = bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


def use_color() -> bool:
    return not _NO_COLOR


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"


def red(t: str) -> str:      return _c("31", t)
def green(t: str) -> str:    return _c("32", t)
def yellow(t: str) -> str:   return _c("33", t)
def blue(t: str) -> str:     return _c("34", t)
def purple(t: str) -> str:   return _c("35", t)
def cyan(t: str) -> str:     return _c("36", t)
def bold(t: str) -> str:     return _c("1", t)
def dim(t: str) -> str:      return _c("2", t)
def bold_red(t: str) -> str: return _c("31;1", t)


SEVERITY_COLOR = {
    "CRITICAL": red,
    "HIGH": bold_red,
    "MEDIUM": yellow,
    "LOW": cyan,
    "INFO": dim,
}


def sev(severity: str) -> str:
    fn = SEVERITY_COLOR.get(severity.upper(), dim)
    return fn(severity.upper())


BANNER = r"""
  ______      __  __
 /_  __/_  __/ /_/ /_  ____ _____
  / / / / / / __/ __ \/ __ `/ __ \
 / / / /_/ / /_/ / / / /_/ / / / /
/_/  \__, /\__/_/ /_/\__,_/_/ /_/
    /____/
"""


def banner(version: str, model: str, workspace: str) -> str:
    lines = [
        cyan(BANNER),
        f"  {bold('Tythan')} v{version} — the AI coding agent that won't ship vulnerabilities",
        f"  {dim('model:')} {model}   {dim('workspace:')} {workspace}",
        f"  {dim('type a request, or /help for commands')}",
        "",
    ]
    return "\n".join(lines)
