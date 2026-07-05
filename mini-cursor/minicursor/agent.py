"""The agent loop: stream a response, execute requested tools, repeat.

Provider-agnostic: all model I/O goes through a Backend, which owns the
native message format. The agent owns tool execution and user confirmation.
"""

from __future__ import annotations

from .checkpoints import CheckpointStore
from .compaction import cap_head, estimate_tokens_heuristic, split_into_rounds
from .config import Config
from .providers.base import Backend, ToolResult
from .tools import MUTATING_TOOLS, TOOL_DEFINITIONS, ToolError, Workspace
from .ui import UI

# Compact when the estimated context in use crosses this fraction of the
# token budget (context window minus the reserved output tokens). Left with
# real headroom below 1.0 because the estimate can be approximate (the
# character-based heuristic fallback) and providers vary in exactly how they
# count tokens.
COMPACT_TRIGGER_RATIO = 0.8

# Floor for the token budget so a tiny/misconfigured context_window can't make
# every single call trigger compaction.
MIN_TOKEN_BUDGET = 1000

# Cap on how much of the old-rounds transcript is fed to the summarization
# call, so compaction itself can't blow up the context it's trying to shrink.
MAX_SUMMARY_INPUT_CHARS = 60_000

SUMMARY_PROMPT = """\
Summarize the earlier part of this coding session so the assistant can keep \
working with full context after older messages are dropped. Be concrete and \
specific:
- what the user has asked for, across all their messages so far
- what has been done in response (files read, files changed and how, \
commands run and their outcome)
- open problems, errors seen, or things still left to do
- any project-specific facts learned along the way (conventions, file \
locations, decisions made, things that didn't work)

Skip pleasantries and internal reasoning. Write it as plain prose working \
memory for the assistant to keep using, not a transcript. Be thorough about \
facts and decisions, but don't pad it out.
"""

SYSTEM_PROMPT = """\
You are mini-cursor, an AI coding assistant running in the user's terminal.
You operate on the user's project workspace via tools: read_file, write_file,
edit_file, list_files, search, run_command.

Guidelines:
- Explore before you change: read the relevant files first so edits match the
  existing code style and edit_file old_string matches exactly.
- Prefer edit_file for small changes; write_file for new files or rewrites.
  Always output complete file contents in write_file — never placeholders.
- Mutating actions (writes, edits, commands) are shown to the user for
  confirmation; a denied action means the user declined it, so adjust your
  approach instead of retrying the same call.
- After making changes, verify them when practical (run tests, run the code).
- Security first: after writing or significantly changing code, run
  security_scan on the touched files and fix CRITICAL/HIGH findings before
  declaring the task done. Never hardcode secrets; read them from env vars.
- Keep answers concise and grounded in what you actually observed in the
  workspace. Lead with the outcome.
"""


class Agent:
    def __init__(
        self,
        config: Config,
        ui: UI,
        backend: Backend,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self.config = config
        self.ui = ui
        self.backend = backend
        self.workspace = Workspace(config.workspace)
        self.messages: list = []
        self.checkpoints = checkpoint_store if checkpoint_store is not None else CheckpointStore(self.workspace.root)
        # Once a compaction attempt fails (e.g. network error during the
        # summarization call), stop retrying it every tool round of the
        # current turn — the underlying call is likely to keep failing, and
        # retrying costs a real API round trip each time.
        self._compaction_unavailable = False

    def reset(self) -> None:
        self.messages = []

    def set_backend(self, backend: Backend) -> None:
        """Switch provider. History is provider-native, so the conversation resets."""
        self.backend = backend
        self.reset()

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT + f"\nWorkspace root: {self.workspace.root}"

    # -- tool dispatch ---------------------------------------------------

    def _execute_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """Run one tool. Returns (output, is_error)."""
        ws = self.workspace
        try:
            if name in MUTATING_TOOLS and not self._approve(name, tool_input):
                return "The user declined this action. Ask them how to proceed or try another approach.", True

            if name == "read_file":
                return ws.read_file(
                    tool_input["path"],
                    offset=tool_input.get("offset", 1),
                    limit=tool_input.get("limit", 2000),
                ), False
            if name == "list_files":
                return ws.list_files(tool_input.get("pattern", "**/*")), False
            if name == "search":
                return ws.search(tool_input["pattern"], tool_input.get("glob", "**/*")), False
            if name == "write_file":
                self._checkpoint_before(tool_input["path"])
                return ws.write_file(tool_input["path"], tool_input["content"]), False
            if name == "edit_file":
                self._checkpoint_before(tool_input["path"])
                return ws.edit_file(
                    tool_input["path"],
                    tool_input["old_string"],
                    tool_input["new_string"],
                    tool_input.get("replace_all", False),
                ), False
            if name == "security_scan":
                from .security import format_findings, scan_workspace

                findings = scan_workspace(ws, tool_input.get("path", "."))
                report = format_findings(findings)
                if tool_input.get("include_dependencies"):
                    from .sca import scan_dependencies

                    dep_findings, note = scan_dependencies(ws.root)
                    report += f"\n\nDependencies: {note}"
                    if dep_findings:
                        report += "\n" + "\n".join(
                            f"[{f.severity}] {f.rule} {f.path} — {f.message}" for f in dep_findings
                        )
                return report, False
            if name == "run_command":
                return ws.run_command(tool_input["command"]), False
            return f"Unknown tool: {name}", True
        except ToolError as exc:
            return str(exc), True
        except KeyError as exc:
            return f"Missing required parameter: {exc}", True

    def _approve(self, name: str, tool_input: dict) -> bool:
        """Show a preview (diff for file changes) and ask the user to confirm."""
        if self.config.yolo:
            return True
        ws = self.workspace
        if name == "write_file":
            target, old = ws.prepare_write(tool_input["path"], tool_input["content"])
            self.ui.show_diff(tool_input["path"], old, tool_input["content"])
            return self.ui.confirm(f"apply changes to {tool_input['path']}?")
        if name == "edit_file":
            _, old, new = ws.prepare_edit(
                tool_input["path"],
                tool_input["old_string"],
                tool_input["new_string"],
                tool_input.get("replace_all", False),
            )
            self.ui.show_diff(tool_input["path"], old, new)
            return self.ui.confirm(f"apply changes to {tool_input['path']}?")
        if name == "run_command":
            return self.ui.confirm(f"run: {tool_input['command']} ?")
        return True

    def _checkpoint_before(self, path: str) -> None:
        """Record `path`'s pre-turn content, if checkpointing is on and the
        path resolves inside the workspace. Never lets checkpointing itself
        block or fail the actual tool call."""
        if not self.config.checkpoints_enabled:
            return
        try:
            target = self.workspace.resolve(path)
        except ToolError:
            return
        try:
            self.checkpoints.record_before(target)
        except OSError:
            pass

    # -- context compaction ------------------------------------------------

    def token_budget(self) -> int:
        """Tokens available for context before the reserved output budget eats
        into the model's context window."""
        return max(self.backend.context_window - self.config.max_tokens, MIN_TOKEN_BUDGET)

    def context_tokens_estimate(self) -> int:
        """Best known estimate of the current history's size in tokens: the
        real usage the backend reported after its last call, or a rough
        character-based heuristic if that isn't available yet."""
        if self.backend.last_context_tokens is not None:
            return self.backend.last_context_tokens
        return estimate_tokens_heuristic(self.messages, self.system_prompt())

    def maybe_compact(self, force: bool = False) -> bool:
        """Summarize older rounds into one message if the context is getting
        full (or always, when `force=True`, e.g. from /compact). Returns
        whether it actually compacted anything."""
        if not force:
            if self._compaction_unavailable:
                return False
            if self.context_tokens_estimate() < self.token_budget() * COMPACT_TRIGGER_RATIO:
                return False

        rounds = split_into_rounds(self.messages)
        keep = max(self.config.compact_keep_rounds, 1)
        if len(rounds) <= keep:
            return False  # nothing old enough to summarize yet

        to_summarize, to_keep = rounds[:-keep], rounds[-keep:]

        try:
            transcript = "\n\n".join(self.backend.render_round(r) for r in to_summarize)
            transcript = cap_head(transcript, MAX_SUMMARY_INPUT_CHARS)
            summary = self.backend.complete_text(SUMMARY_PROMPT, transcript)
        except Exception as exc:
            self._compaction_unavailable = True
            self.ui.error(f"context compaction unavailable ({exc}); continuing with full history")
            return False

        flat_keep = [m for r in to_keep for m in r]
        prefix = (
            f"[Summary of {len(to_summarize)} earlier turn(s), compacted to save context]\n"
            f"{summary.strip()}\n[end summary]\n\n"
        )
        if flat_keep and flat_keep[0].get("role") == "user" and isinstance(flat_keep[0].get("content"), str):
            flat_keep[0] = {**flat_keep[0], "content": prefix + flat_keep[0]["content"]}
        else:
            flat_keep.insert(0, {"role": "user", "content": prefix.strip()})

        before_count = len(self.messages)
        self.messages = flat_keep
        # Stale now that history changed shape; recomputed on the next real call.
        self.backend.last_context_tokens = None
        self.ui.info(
            f"context compacted: {before_count} -> {len(self.messages)} message(s) "
            f"({len(to_summarize)} earlier turn(s) summarized)"
        )
        return True

    # -- the loop ----------------------------------------------------------

    def run_turn(self, user_input: str) -> None:
        """Process one user message to completion (may involve many tool rounds)."""
        self.backend.add_user_message(self.messages, user_input)
        self.ui.assistant_prefix()
        self.checkpoints.begin_turn(user_input)
        self._compaction_unavailable = False

        try:
            while True:
                self.maybe_compact()

                result = self.backend.stream_turn(
                    self.messages, self.system_prompt(), TOOL_DEFINITIONS, self.ui
                )

                if result.stop == "refusal":
                    self.ui.error("The request was declined by the model's safety system. Try rephrasing.")
                    return

                if result.stop == "length":
                    self.ui.error("Response hit the output token limit; it may be incomplete.")

                if not result.tool_calls:
                    if result.usage:
                        self.ui.info(f"tokens: {result.usage}")
                    return

                results = []
                for call in result.tool_calls:
                    self.ui.tool_call(call.name, call.input)
                    output, is_error = self._execute_tool(call.name, call.input)
                    self.ui.tool_result(output, is_error)
                    results.append(ToolResult(call_id=call.id, output=output, is_error=is_error))
                self.backend.add_tool_results(self.messages, results)
        finally:
            checkpoint = self.checkpoints.commit_turn()
            if checkpoint:
                note = ""
                if checkpoint.skipped_large:
                    note = f" ({len(checkpoint.skipped_large)} large file(s) not covered)"
                self.ui.info(
                    f"checkpoint saved: {len(checkpoint.changes)} file(s) changed{note} — /undo to revert"
                )
