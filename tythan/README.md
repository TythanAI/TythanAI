# Tythan — the AI coding agent that won't ship vulnerabilities

A Cursor-style agentic coding assistant that lives in your terminal. Chat
with a model about your project; it reads your code, edits files and runs
commands — every change shown as a colorized diff you approve, and every
change **security-scanned before it touches disk**.

```bash
pip install tythanai-community
export ANTHROPIC_API_KEY=sk-ant-…
cd your-project
tythan
```

```
  ______      __  __
 /_  __/_  __/ /_/ /_  ____ _____
  / / / / / / __/ __ \/ __ `/ __ \
 / / / /_/ / /_/ / / / /_/ / / / /
/_/  \__, /\__/_/ /_/\__,_/_/ /_/
    /____/
  Tythan v0.1.0 — the AI coding agent that won't ship vulnerabilities
  model: anthropic/claude-opus-4-8   workspace: /home/you/your-project

tythan> add rate limiting to the login endpoint
```

## Why another coding agent

Claude Code, Aider and Codex CLI will happily write you an endpoint with an
f-string SQL query, a hardcoded API key, or `verify=False`. Tythan is built
by a security company and treats that as a bug in the *agent*, not in your
review process:

- **Security gate on every write.** Before an AI-authored `write_file` /
  `edit_file` reaches disk, the changed lines are scanned for leaked
  secrets, injection-prone code, disabled TLS verification, weak crypto and
  insecure config. Findings are shown in the approval diff; **CRITICAL
  findings block the write outright** — the agent gets the report and must
  rewrite the change safely. Only lines *introduced by the change* are
  gated, so pre-existing issues never block an unrelated edit.
- **The gate holds even in `--yolo` mode.** Auto-approve skips the y/n
  prompt, not the scanner.
- **`/audit`** runs the scanner across the workspace any time; the agent
  also has it as a `security_scan` tool, so you can ask *"scan the project
  and fix what you find"*. Deeper analysis (full SAST rule set, dependency
  CVEs, Web3 auditing) is one command away: `tythanai scan .` — same
  package.

## Features

- **Agentic edits with real diffs** — the model reads/searches your code,
  proposes changes; you see a colorized unified diff and confirm. Commands
  (`run_command`) are confirmed the same way.
- **Undo** — every turn's file changes are checkpointed; `/undo` reverts
  the whole turn. Files that are too large or not valid UTF-8 are skipped
  rather than checkpointed, so undo can never restore a corrupted copy.
- **Workspace-confined** — every path the model supplies is resolved
  against the workspace root; escapes (including via symlinks) are
  rejected.
- **Automatic context compaction** — long sessions don't die with a
  context-length error: older rounds get summarized, recent rounds stay
  verbatim. `/compact` and `/context` for manual control.
- **Project rules files** — `.tythanrules`, `.cursorrules` (existing Cursor
  projects keep working unchanged) or `AGENTS.md` at the workspace root are
  appended to the system prompt on every turn.
- **Any model** — native Anthropic (streaming, adaptive thinking + effort),
  or any OpenAI-compatible endpoint: OpenAI, OpenRouter, Groq, DeepSeek,
  local models via Ollama / LM Studio / vLLM.
- **One-shot mode** — `tythan -p "explain the auth flow"` (or pipe stdin)
  for scripting; writes/commands are denied unless `--yolo`.

## Usage

```bash
tythan                                  # interactive REPL in the current dir
tythan -w ~/code/project                # different workspace
tythan -p "why does test_login fail?"   # one-shot question

# Providers
tythan --provider anthropic --model claude-opus-4-8      # default
tythan --provider openai --model gpt-5.2
tythan --provider openrouter --model anthropic/claude-opus-4.8
tythan --provider ollama --model qwen3-coder             # local
tythan --provider custom --base-url http://localhost:8000/v1 --model my-model
```

API keys come from the environment only (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `TYTHAN_API_KEY`) — tythan never
writes them to disk.

### Slash commands

| Command | Effect |
|---|---|
| `/help` | list commands |
| `/model <id>` | switch model id |
| `/undo` | revert the last turn's file changes |
| `/checkpoints` | list undo checkpoints |
| `/audit [path]` | security-scan the workspace (or a path) |
| `/yolo` | toggle auto-approve (the CRITICAL gate still applies) |
| `/compact` | compact conversation context now |
| `/context` | show estimated context usage |
| `/clear` | fresh conversation |
| `/quit` | exit |

### Flags worth knowing

| Flag | Effect |
|---|---|
| `--yolo` | auto-approve writes/commands (CRITICAL findings still block) |
| `--allow-critical` | let CRITICAL findings through (reported, not blocked) |
| `--no-security-gate` | disable pre-write scanning entirely |
| `--effort low…max` | reasoning effort (Anthropic models) |
| `--context-window N` | override the assumed context window (local servers often run small) |
| `--max-turns N` | cap tool rounds per message (default 40) |

## What the security gate catches

A compact, dependency-free distillation of the TythanAI scanners: AWS /
GitHub / Slack / OpenAI / Anthropic keys and private-key blocks, hardcoded
passwords and high-entropy credential assignments, `eval`/`exec`,
`pickle.loads`, unsafe `yaml.load`, `shell=True`, SQL built with
f-strings/template literals, `verify=False` and unverified TLS contexts,
weak hashes, `random` used for tokens, `child_process` exec interpolation,
innerHTML/XSS sinks, wildcard CORS, JWT `none`, debug mode and 0.0.0.0
binds. Run `tythanai scan .` for the full pipeline (Semgrep SAST, OSV.dev
dependency CVEs, IaC, TON/Solana/CosmWasm/Solidity auditing).

## Limitations (said plainly)

- The per-write gate is regex-based: fast, offline and predictable, but it
  is a tripwire, not a program analysis. It will miss taint that flows
  across lines and files — that's what `tythanai scan` / Pro is for.
- `run_command` isn't covered by undo; there's no honest way to snapshot an
  arbitrary shell command's effects. Checkpoints cover
  `write_file`/`edit_file`, which tythan fully controls.
- Sessions are in-memory: quitting ends the conversation (checkpoints too).
  Persistent sessions are on the roadmap.

## Development

```bash
pip install -e . && pip install pytest
python -m pytest tests/tythan/ -q      # 97 offline tests, no API key needed
```

Architecture: `tythan/` is a small, flat package — `cli.py` (REPL, diff
approval UX), `agent.py` (tool loop + gate wiring), `providers.py`
(Anthropic SDK + OpenAI-compatible SSE), `tools.py` (workspace-confined
file/shell tools), `security_gate.py`, `checkpoints.py`, `compaction.py`,
`rules.py`. Everything except `cli.py` is exercised by the offline test
suite with fake backends.
