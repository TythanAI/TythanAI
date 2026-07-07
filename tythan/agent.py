# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/agent.py — the tool-execution loop.

One `Agent.run_user_turn()` call handles a full user request: it sends the
conversation to the model, executes the tools the model asks for (routing
every mutation through the approver + security gate), feeds results back,
and repeats until the model answers in plain text or the round limit hits.

The Approver protocol is how the UI plugs in: the CLI shows a colorized
diff and asks y/n; tests supply a scripted approver; --yolo approves
everything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from tythan import security_gate
from tythan.checkpoints import CheckpointStore
from tythan.compaction import (
    SUMMARY_PROMPT,
    compact,
    needs_compaction,
    split_rounds,
    transcript_for_summary,
)
from tythan.config import Config
from tythan.providers import Backend, BackendError, ToolCall
from tythan.rules import load_rules
from tythan.tools import TOOL_SPECS, ProposedWrite, ToolError, Workspace

SYSTEM_PROMPT = """\
You are Tythan, an AI coding agent running in the user's terminal, made by \
TythanAI. You help with software engineering tasks in the workspace at {root}.

Rules:
- Use the tools to read files and gather context before editing; never guess \
file contents.
- Prefer edit_file (exact string replacement) for changes to existing files; \
write_file only for new files or full rewrites.
- Every write_file/edit_file result is security-scanned. If the result reports \
findings on lines you introduced, fix them before moving on — never ship \
hardcoded secrets, injection-prone string building, disabled TLS verification \
or similar vulnerabilities.
- The user approves every file change and command. If an action was denied, \
respect that decision: adjust your approach instead of retrying it verbatim.
- Keep answers concise and terminal-friendly. When you finish a task, briefly \
summarize what changed.\
"""


class Approver(Protocol):
    def approve_write(self, write: ProposedWrite,
                      findings: list[security_gate.Finding]) -> bool: ...
    def approve_command(self, command: str) -> bool: ...


class YoloApprover:
    """Approves everything except gate-blocked writes (handled by the agent)."""
    def approve_write(self, write, findings) -> bool:
        return True
    def approve_command(self, command) -> bool:
        return True


@dataclass
class TurnStats:
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    files_changed: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.files_changed is None:
            self.files_changed = []


class Agent:
    def __init__(self, config: Config, workspace: Workspace, backend: Backend,
                 approver: Approver,
                 on_notice: Callable[[str], None] = lambda s: None) -> None:
        self.config = config
        self.workspace = workspace
        self.backend = backend
        self.approver = approver
        self.on_notice = on_notice          # short status lines for the UI
        self.history: list[dict] = []
        self.checkpoints = CheckpointStore()
        self.last_usage = (0, 0)

    # ── Public API ───────────────────────────────────────────────────────

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(root=self.workspace.root) \
            + load_rules(self.workspace.root)

    def run_user_turn(self, user_message: str,
                      on_text: Callable[[str], None]) -> TurnStats:
        stats = TurnStats()
        system = self.system_prompt()
        self._maybe_compact(system)
        self.history.append({"role": "user", "content": user_message})
        self.checkpoints.begin_turn(label=user_message[:80])
        try:
            for _ in range(self.config.max_turns):
                stats.rounds += 1
                result = self.backend.run_turn(system, self.history, TOOL_SPECS, on_text)
                stats.input_tokens += result.input_tokens
                stats.output_tokens += result.output_tokens
                self.last_usage = (result.input_tokens, result.output_tokens)
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in result.tool_calls
                    ],
                }
                if result.raw_assistant is not None:
                    assistant_msg["_raw"] = result.raw_assistant
                self.history.append(assistant_msg)
                if not result.tool_calls:
                    break
                # Every tool_use must get a tool_result, even if one raises
                # or the user aborts mid-round — otherwise the next request
                # is malformed.
                answered: set[str] = set()
                try:
                    for tc in result.tool_calls:
                        output, is_error, changed = self._execute(tc)
                        if changed:
                            stats.files_changed.append(changed)
                        self.history.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "name": tc.name, "content": output,
                            **({"is_error": True} if is_error else {}),
                        })
                        answered.add(tc.id)
                finally:
                    for tc in result.tool_calls:
                        if tc.id not in answered:
                            self.history.append({
                                "role": "tool", "tool_call_id": tc.id,
                                "name": tc.name, "is_error": True,
                                "content": "(tool call aborted before completion)",
                            })
            else:
                self.on_notice(f"stopped after {self.config.max_turns} tool rounds")
        finally:
            self.checkpoints.commit_turn()
        return stats

    def undo_last(self) -> tuple[list[str], list[str]]:
        restored, problems = self.checkpoints.undo_last()
        if restored:
            self.history.append({
                "role": "user",
                "content": "[The user reverted your last file changes with /undo: "
                           + ", ".join(restored) + "]",
            })
        return restored, problems

    def context_usage(self) -> tuple[int, int]:
        from tythan.compaction import estimate_tokens
        used = estimate_tokens(self.history, extra_chars=len(self.system_prompt()))
        return used, self.config.context_window

    def compact_now(self) -> bool:
        return self._compact(self.system_prompt(), force=True)

    # ── Tool dispatch ────────────────────────────────────────────────────

    def _execute(self, tc: ToolCall) -> tuple[str, bool, str | None]:
        """Returns (output, is_error, changed_file_display_path)."""
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        try:
            if tc.name == "read_file":
                return self.workspace.read_file(
                    str(args.get("path", "")),
                    int(args.get("offset") or 0), int(args.get("limit") or 0)), False, None
            if tc.name == "list_dir":
                return self.workspace.list_dir(str(args.get("path") or ".")), False, None
            if tc.name == "glob":
                return self.workspace.glob(str(args.get("pattern", ""))), False, None
            if tc.name == "grep":
                return self.workspace.grep(
                    str(args.get("pattern", "")), str(args.get("include") or "")), False, None
            if tc.name == "write_file":
                write = self.workspace.propose_write(
                    str(args.get("path", "")), str(args.get("content", "")))
                return self._apply_write(write)
            if tc.name == "edit_file":
                write = self.workspace.propose_edit(
                    str(args.get("path", "")), str(args.get("old_string", "")),
                    str(args.get("new_string", "")), bool(args.get("replace_all")))
                return self._apply_write(write)
            if tc.name == "run_command":
                command = str(args.get("command", ""))
                if not self.config.yolo and not self.approver.approve_command(command):
                    return "(user denied running this command)", True, None
                timeout = int(args.get("timeout") or self.config.command_timeout)
                timeout = max(1, min(timeout, 600))
                return self.workspace.run_command(command, timeout), False, None
            if tc.name == "security_scan":
                findings = security_gate.scan_path(
                    self.workspace.root, str(args.get("path") or "."))
                return security_gate.format_report(findings), False, None
            return f"unknown tool {tc.name!r}", True, None
        except ToolError as exc:
            return f"tool error: {exc}", True, None
        except Exception as exc:  # tool bugs must not kill the session
            return f"unexpected tool failure: {type(exc).__name__}: {exc}", True, None

    def _apply_write(self, write: ProposedWrite) -> tuple[str, bool, str | None]:
        findings: list[security_gate.Finding] = []
        if self.config.security_gate:
            findings = security_gate.scan_change(
                write.old_content, write.new_content, write.display_path)
        worst = security_gate.worst_severity(findings)
        if self.config.security_gate and self.config.block_critical and worst == "CRITICAL":
            report = "\n".join(f.format() for f in findings)
            return ("BLOCKED by the security gate — this change introduces "
                    f"CRITICAL findings:\n{report}\n"
                    "Rewrite the change without these vulnerabilities."), True, None
        if not self.config.yolo:
            if not self.approver.approve_write(write, findings):
                return "(user rejected this change after reviewing the diff)", True, None
        self.checkpoints.record(write.path)
        try:
            Workspace.apply_write(write)
        except OSError as exc:
            return f"write failed: {exc}", True, None
        note = f"wrote {write.display_path}"
        if findings:
            report = "\n".join(f.format() for f in findings[:10])
            note += (f"\nsecurity gate: {len(findings)} finding(s) introduced "
                     f"by this change:\n{report}\nFix any HIGH findings.")
        return note, False, write.display_path

    # ── Compaction ───────────────────────────────────────────────────────

    def _maybe_compact(self, system: str) -> None:
        if needs_compaction(self.history, self.config.context_window,
                            self.config.max_output_tokens, len(system)):
            self._compact(system)

    def _compact(self, system: str, force: bool = False) -> bool:
        rounds = split_rounds(self.history)
        keep = 2
        if len(rounds) <= keep:
            return False
        to_summarize = rounds[:-keep]
        transcript = transcript_for_summary(to_summarize)
        self.on_notice("compacting context…")
        try:
            summary = self.backend.summarize(SUMMARY_PROMPT + transcript)
        except BackendError as exc:
            self.on_notice(f"compaction failed ({exc}); continuing uncompacted")
            return False
        if not summary.strip():
            self.on_notice("compaction produced an empty summary; skipped")
            return False
        before = len(self.history)
        self.history = compact(self.history, summary, keep_rounds=keep)
        self.on_notice(f"context compacted: {before} → {len(self.history)} messages")
        return True


def format_tool_call(tc: ToolCall) -> str:
    """One-line human-readable rendering of a tool call for the UI."""
    args = tc.arguments or {}
    key_bits = []
    for key in ("path", "pattern", "command"):
        if key in args:
            val = str(args[key])
            key_bits.append(val if len(val) <= 80 else val[:77] + "…")
    if not key_bits and args:
        key_bits.append(json.dumps(args, ensure_ascii=False)[:80])
    return f"{tc.name}({', '.join(key_bits)})"
