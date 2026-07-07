# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/cli.py — the `tythan` command.

Interactive REPL (default) or one-shot mode (`tythan -p "..."`).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tythan
from tythan import security_gate, ui
from tythan.agent import Agent, YoloApprover
from tythan.config import PROVIDERS, Config
from tythan.diffview import render_diff
from tythan.providers import BackendError, make_backend
from tythan.tools import ProposedWrite, Workspace

HELP = """\
Commands:
  /help                 show this help
  /model <id>           switch model id (same provider)
  /undo                 revert the last turn's file changes
  /checkpoints          list undo checkpoints
  /audit [path]         run the security scanner on the workspace (or path)
  /yolo                 toggle auto-approve of writes/commands
  /compact              compact conversation context now
  /context              show estimated context usage
  /clear                start a fresh conversation (undo history is kept)
  /quit                 exit (also Ctrl+D)
Anything else is sent to the model. Ctrl+C aborts the current generation.\
"""


class ConsoleApprover:
    """Shows the diff / command and asks the user to confirm."""

    def approve_write(self, write: ProposedWrite,
                      findings: list[security_gate.Finding]) -> bool:
        print()
        print(render_diff(write.old_content, write.new_content, write.display_path))
        for f in findings:
            print(ui.sev(f.severity) + " " + f.title + ui.dim(f"  ({f.file}:{f.line})"))
        if findings:
            print(ui.yellow("This change introduces the finding(s) above."))
        return _ask(f"Apply changes to {write.display_path}?")

    def approve_command(self, command: str) -> bool:
        print()
        print(ui.bold("── run command ") + "\n" + ui.cyan("$ " + command))
        return _ask("Run this command?")


class DenyAllApprover:
    """Non-interactive runs without --yolo can't approve anything."""
    def approve_write(self, write, findings) -> bool:
        return False
    def approve_command(self, command) -> bool:
        return False


def _ask(question: str) -> bool:
    try:
        answer = input(ui.bold(f"{question} [y/N] ")).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tythan",
        description="Tythan — the AI coding agent that won't ship vulnerabilities.",
    )
    parser.add_argument("-p", "--prompt", help="run one prompt and exit (non-interactive)")
    parser.add_argument("-w", "--workspace", default=".", help="workspace root (default: cwd)")
    parser.add_argument("--provider", default="anthropic", choices=PROVIDERS)
    parser.add_argument("--model", default="", help="model id for the provider")
    parser.add_argument("--base-url", default="", help="override the provider base URL")
    parser.add_argument("--effort", default="high",
                        choices=("low", "medium", "high", "xhigh", "max"),
                        help="reasoning effort (Anthropic models)")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--context-window", type=int, default=0,
                        help="override the assumed context window in tokens")
    parser.add_argument("--max-turns", type=int, default=40,
                        help="max tool rounds per user message")
    parser.add_argument("--yolo", action="store_true",
                        help="auto-approve every write/command (dangerous)")
    parser.add_argument("--no-security-gate", action="store_true",
                        help="disable pre-write security scanning")
    parser.add_argument("--allow-critical", action="store_true",
                        help="don't block writes with CRITICAL security findings")
    parser.add_argument("--version", action="version",
                        version=f"tythan {tythan.__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config(
            provider=args.provider, model=args.model, base_url=args.base_url,
            effort=args.effort, max_output_tokens=args.max_output_tokens,
            context_window=args.context_window, max_turns=args.max_turns,
            yolo=args.yolo, security_gate=not args.no_security_gate,
            block_critical=not args.allow_critical,
        )
        config.require_api_key()
        workspace = Workspace(Path(args.workspace).resolve())
        backend = make_backend(config)
    except (ValueError, BackendError) as exc:
        print(ui.red(f"error: {exc}"), file=sys.stderr)
        return 2

    interactive = args.prompt is None and sys.stdin.isatty()
    if config.yolo:
        approver = YoloApprover()
    elif interactive or sys.stdin.isatty():
        approver = ConsoleApprover()
    else:
        approver = DenyAllApprover()

    printer = _Printer()
    agent = Agent(config, workspace, backend, approver, on_notice=printer.notice)

    if args.prompt is not None:
        return _one_shot(agent, printer, args.prompt)
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if not data:
            print(ui.red("error: no prompt given (use -p or pipe stdin)"), file=sys.stderr)
            return 2
        return _one_shot(agent, printer, data)
    return _repl(agent, printer, config, workspace)


class _Printer:
    """Streams model text and injects status notices on their own lines."""

    def __init__(self) -> None:
        self._midline = False

    def text(self, piece: str) -> None:
        if piece:
            print(piece, end="", flush=True)
            self._midline = not piece.endswith("\n")

    def notice(self, message: str) -> None:
        if self._midline:
            print()
            self._midline = False
        if "BLOCKED" in message:
            print(ui.red(f"✘ {message}"))
        else:
            print(ui.dim(f"· {message}"))


def _one_shot(agent: Agent, printer: _Printer, prompt: str) -> int:
    if not agent.config.yolo:
        print(ui.dim("· non-interactive run without --yolo: file writes and "
                      "commands will be denied"), file=sys.stderr)
    try:
        agent.run_user_turn(prompt, printer.text)
    except BackendError as exc:
        print(ui.red(f"\nerror: {exc}"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(ui.dim("\n(aborted)"))
        return 130
    print()
    return 0


def _repl(agent: Agent, printer: _Printer, config: Config, workspace: Workspace) -> int:
    try:
        import readline  # noqa: F401 — line editing + history for input()
    except ImportError:
        pass
    print(ui.banner(tythan.__version__, f"{config.provider}/{config.model}",
                    str(workspace.root)))
    while True:
        try:
            line = input(ui.bold(ui.cyan("tythan> "))).strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue
        if not line:
            continue
        if line.startswith("/"):
            if _slash(agent, config, line) == "quit":
                return 0
            continue
        try:
            print()
            stats = agent.run_user_turn(line, printer.text)
            print()
            bits = [f"{stats.rounds} round(s)"]
            if stats.files_changed:
                bits.append(f"changed: {', '.join(dict.fromkeys(stats.files_changed))}")
            if stats.input_tokens or stats.output_tokens:
                bits.append(f"tokens {stats.input_tokens}in/{stats.output_tokens}out")
            print(ui.dim("· " + " · ".join(bits)))
        except BackendError as exc:
            print(ui.red(f"\nerror: {exc}"))
        except KeyboardInterrupt:
            print(ui.dim("\n(generation aborted; conversation is still usable)"))
    return 0


def _slash(agent: Agent, config: Config, line: str) -> str | None:
    cmd, _, rest = line.partition(" ")
    rest = rest.strip()
    if cmd in ("/quit", "/exit", "/q"):
        return "quit"
    if cmd == "/help":
        print(HELP)
    elif cmd == "/model":
        if rest:
            config.model = rest
            print(f"model → {config.model}")
        else:
            print(f"model: {config.model} (usage: /model <id>)")
    elif cmd == "/undo":
        restored, problems = agent.undo_last()
        for r in restored:
            print(ui.green(f"restored {r}"))
        for p in problems:
            print(ui.yellow(p))
    elif cmd == "/checkpoints":
        entries = agent.checkpoints.list()
        print("\n".join(entries) if entries else "(no checkpoints)")
    elif cmd == "/audit":
        target = rest or "."
        print(ui.dim(f"· scanning {rest or 'workspace'}…"))
        findings = security_gate.scan_path(agent.workspace.root, target)
        if not findings:
            print(ui.green("No security findings."))
        else:
            for f in findings[:100]:
                print(ui.sev(f.severity) + f" {f.title}  " + ui.dim(f"{f.file}:{f.line}"))
            if len(findings) > 100:
                print(ui.dim(f"… and {len(findings) - 100} more"))
            print(ui.dim("· deeper analysis (SAST/SCA/Web3): pip install "
                         "tythanai-community && tythanai scan ."))
    elif cmd == "/yolo":
        config.yolo = not config.yolo
        state = "ON — every write/command auto-approved" if config.yolo else "off"
        print(ui.yellow(f"yolo mode {state}"))
    elif cmd == "/compact":
        if not agent.compact_now():
            print("(nothing to compact)")
    elif cmd == "/context":
        used, window = agent.context_usage()
        pct = 100 * used // max(window, 1)
        print(f"~{used:,} of {window:,} tokens ({pct}%)")
    elif cmd == "/clear":
        agent.history = []
        print("(conversation cleared)")
    else:
        print(f"unknown command {cmd!r} — /help for the list")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
