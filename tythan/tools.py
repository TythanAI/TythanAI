# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/tools.py — workspace-confined tools the agent can call.

Every path is resolved against the workspace root (symlinks included) and
anything that escapes it is rejected. Mutating tools (write_file, edit_file,
run_command) never act directly — the agent routes them through an approver
so the user confirms a diff (or command) first.
"""
from __future__ import annotations

import fnmatch
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_READ_BYTES = 256 * 1024        # per read_file call
MAX_RESULT_CHARS = 40_000          # cap any tool result fed back to the model
MAX_GREP_MATCHES = 200
MAX_LIST_ENTRIES = 500

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".ruff_cache", "dist", "build", ".next", ".tox", ".eggs", "target",
}


class ToolError(Exception):
    """Raised for invalid tool input; reported to the model, never fatal."""


@dataclass
class ProposedWrite:
    """A file mutation awaiting user approval."""
    path: Path                 # absolute, confined
    display_path: str          # workspace-relative, for humans
    old_content: str | None    # None = file doesn't exist yet
    new_content: str


class Workspace:
    """Path confinement plus the read-only tool implementations."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace root {self.root} is not a directory")

    # ── Confinement ──────────────────────────────────────────────────────

    def resolve(self, rel_path: str) -> Path:
        """Resolve a model-supplied path inside the workspace or raise."""
        if not rel_path or rel_path.strip() == "":
            raise ToolError("path must be a non-empty string")
        p = Path(rel_path)
        candidate = p if p.is_absolute() else self.root / p
        # Resolve the deepest existing ancestor so symlinks can't smuggle
        # a path out of the workspace before the file even exists.
        existing = candidate
        tail: list[str] = []
        while not existing.exists() and existing != existing.parent:
            tail.append(existing.name)
            existing = existing.parent
        resolved = existing.resolve()
        for part in reversed(tail):
            if part in ("..", "."):
                raise ToolError(f"path {rel_path!r} escapes the workspace")
            resolved = resolved / part
        if resolved != self.root and self.root not in resolved.parents:
            raise ToolError(f"path {rel_path!r} escapes the workspace")
        return resolved

    def display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    # ── Read-only tools ──────────────────────────────────────────────────

    def read_file(self, path: str, offset: int = 0, limit: int = 0) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"{path!r} is not a file")
        if p.stat().st_size > MAX_READ_BYTES and not limit:
            limit = 2_000
        try:
            text = p.read_text("utf-8", errors="replace")
        except OSError as exc:
            raise ToolError(f"cannot read {path!r}: {exc}") from exc
        lines = text.splitlines()
        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]
        numbered = [f"{i + 1 + (offset or 0):>6}\t{line}" for i, line in enumerate(lines)]
        return _cap("\n".join(numbered) or "(empty file)")

    def list_dir(self, path: str = ".") -> str:
        p = self.resolve(path or ".")
        if not p.is_dir():
            raise ToolError(f"{path!r} is not a directory")
        entries = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if child.name in _SKIP_DIRS:
                continue
            entries.append(child.name + ("/" if child.is_dir() else ""))
            if len(entries) >= MAX_LIST_ENTRIES:
                entries.append("… (truncated)")
                break
        return _cap("\n".join(entries) or "(empty directory)")

    def glob(self, pattern: str) -> str:
        if not pattern:
            raise ToolError("pattern must be a non-empty string")
        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), self.root)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                    matches.append(rel)
                    if len(matches) >= MAX_LIST_ENTRIES:
                        matches.append("… (truncated)")
                        return _cap("\n".join(matches))
        return _cap("\n".join(sorted(matches)) or "(no matches)")

    def grep(self, pattern: str, include: str = "") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from exc
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                if include and not fnmatch.fnmatch(name, include):
                    continue
                fp = Path(dirpath) / name
                try:
                    if fp.stat().st_size > 2 * 1024 * 1024:
                        continue
                    text = fp.read_text("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel = os.path.relpath(fp, self.root)
                for lineno, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                        if len(out) >= MAX_GREP_MATCHES:
                            out.append("… (truncated)")
                            return _cap("\n".join(out))
        return _cap("\n".join(out) or "(no matches)")

    # ── Mutating tools: build a ProposedWrite for the approver ───────────

    def propose_write(self, path: str, content: str) -> ProposedWrite:
        p = self.resolve(path)
        old: str | None = None
        if p.exists():
            if not p.is_file():
                raise ToolError(f"{path!r} exists and is not a regular file")
            try:
                old = p.read_text("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ToolError(f"cannot rewrite {path!r}: {exc}") from exc
        return ProposedWrite(p, self.display(p), old, content)

    def propose_edit(self, path: str, old_string: str, new_string: str,
                     replace_all: bool = False) -> ProposedWrite:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"{path!r} is not a file")
        if old_string == new_string:
            raise ToolError("old_string and new_string are identical")
        try:
            text = p.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"cannot edit {path!r}: {exc}") from exc
        count = text.count(old_string)
        if count == 0:
            raise ToolError(f"old_string not found in {path!r}")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string occurs {count} times in {path!r}; "
                "make it unique or set replace_all=true"
            )
        new_text = text.replace(old_string, new_string) if replace_all \
            else text.replace(old_string, new_string, 1)
        return ProposedWrite(p, self.display(p), text, new_text)

    @staticmethod
    def apply_write(w: ProposedWrite) -> None:
        w.path.parent.mkdir(parents=True, exist_ok=True)
        w.path.write_text(w.new_content, "utf-8")

    # ── Shell ────────────────────────────────────────────────────────────

    def run_command(self, command: str, timeout: int = 120) -> str:
        """Run a shell command in the workspace. Kills the whole process
        group on timeout so hung children don't outlive the call."""
        if not command.strip():
            raise ToolError("command must be a non-empty string")
        kwargs: dict = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            command, shell=True, cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            **kwargs,
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            else:
                proc.kill()
            proc.wait()
            return f"(command timed out after {timeout}s and was killed)"
        result = out or ""
        status = f"(exit code {proc.returncode})"
        return _cap(f"{result.rstrip()}\n{status}" if result.strip() else status)


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (truncated, {len(text) - limit} chars omitted)"


# ── Tool schema (provider-neutral; providers translate it) ───────────────

TOOL_SPECS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace. Returns numbered lines. "
                       "Use offset/limit for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "offset": {"type": "integer", "description": "Line to start from (0-based)"},
                "limit": {"type": "integer", "description": "Max lines to return"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory in the workspace. Directories end with '/'.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, default '.'"}},
            "required": [],
        },
    },
    {
        "name": "glob",
        "description": "Find files by glob pattern (e.g. '**/*.py', 'src/*.ts').",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents with a regular expression. "
                       "Optionally filter files with an 'include' glob (e.g. '*.py').",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "include": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file. The user sees a diff and must "
                       "approve before anything is written. The content is also "
                       "security-scanned; fix any CRITICAL finding it reports.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace an exact string in a file (must match uniquely unless "
                       "replace_all). The user sees a diff and must approve. The result "
                       "is security-scanned; fix any CRITICAL finding it reports.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the workspace root. The user must "
                       "approve it first. Output is combined stdout+stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds, default 120"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "security_scan",
        "description": "Scan a file or the whole workspace for security issues "
                       "(secrets, dangerous code patterns, insecure config). "
                       "Returns findings with severity and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory, default '.'"},
            },
            "required": [],
        },
    },
]
