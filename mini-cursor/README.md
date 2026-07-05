# mini-cursor

**The AI coding agent that won't ship vulnerabilities.**

A Cursor-style AI coding assistant that lives in your terminal — with **any
model you want** and a **built-in security auditor**. Chat about your project;
the assistant reads and edits files, searches the codebase, runs shell
commands, and scans its own output for security issues before calling a task
done. Every file change is shown as a diff and every command waits for your
confirmation.

```
             _       _
  _ __ ___  (_)_ __ (_)       ___ _   _ _ __ ___  ___  _ __
 | '_ ` _ \ | | '_ \| |_____ / __| | | | '__/ __|/ _ \| '__|
 | | | | | || | | | | |_____| (__| |_| | |  \__ \ (_) | |
 |_| |_| |_||_|_| |_|_|      \___|\__,_|_|  |___/\___/|_|
```

## Features

- **Security-first agent** — the `security_scan` tool detects leaked secrets
  and API keys (AWS, GitHub, Stripe, Google, Slack, Telegram, JWTs, Bearer
  tokens + a Shannon-entropy detector for everything else), dangerous code
  patterns (eval, pickle, SQL built from f-strings, `shell=True`,
  `verify=False`, weak ciphers, `random` used for secrets, ...) and insecure
  config (wildcard CORS, JWT `none`, debug mode, plain-http endpoints). The
  agent audits code it just wrote and fixes CRITICAL/HIGH findings before
  declaring a task done; run `/audit` any time for an instant offline report.
- **Dependency CVE check (SCA)** — pinned dependencies from
  `requirements.txt`, `pyproject.toml` and `package.json` are checked against
  the [OSV.dev](https://osv.dev) vulnerability database (free, no key).
  Included in `/audit`; the agent can request it via
  `security_scan(include_dependencies=true)`. Degrades gracefully offline.
- **Any model** — native Anthropic API plus *any* OpenAI-compatible endpoint:
  OpenAI, OpenRouter, Groq, DeepSeek, Mistral, xAI, and fully local models via
  Ollama / LM Studio / vLLM. Switch providers mid-session with `/provider`.
- **Agentic loop** — the model reads files, edits them, runs tests and
  iterates until the task is done, streaming its answer live.
- **Human in the loop** — writes/edits show a colored unified diff and ask
  `[y/N]`; shell commands ask before running. `--yolo` turns this off.
- **`@file` mentions** — type `@src/app.py` in your message to attach that
  file's contents.
- **Workspace-confined** — all file operations are locked inside the project
  directory; path traversal is rejected.
- **Tools** — `read_file`, `write_file`, `edit_file` (exact string replace),
  `list_files` (glob), `search` (regex), `run_command`.
- **Undo (`/undo`)** — every `write_file`/`edit_file` is checkpointed before it
  runs. `/undo` reverts the whole last turn's file changes in one step,
  survives restarting mini-cursor, and stays out of the way otherwise: nothing
  is written to `~/.minicursor` until a file actually changes. Shell commands
  run via `run_command` aren't covered — there's no honest way to snapshot and
  revert arbitrary shell effects, so this is a safety net for agent-authored
  edits, not a full undo of everything the agent does.
- **Automatic context compaction** — long sessions don't hit a hard
  context-length error. When the conversation approaches the model's context
  window, mini-cursor summarizes the older turns into one message and keeps
  the most recent turns verbatim, so the assistant keeps working instead of
  failing outright. Trigger it manually with `/compact`, check usage with
  `/context`.

## Install

```bash
cd mini-cursor
pip install .
```

Requires Python 3.10+. For the default Anthropic provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or: ant auth login   (the SDK picks the profile up automatically)
```

## Providers

On first run mini-cursor creates `~/.minicursor/config.json`:

```json
{
  "default_provider": "anthropic",
  "providers": {
    "anthropic":  {"type": "anthropic", "model": "claude-opus-4-8"},
    "openai":     {"type": "openai", "base_url": "https://api.openai.com/v1",
                   "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o"},
    "openrouter": {"type": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "api_key_env": "OPENROUTER_API_KEY", "model": "anthropic/claude-sonnet-4.5"},
    "ollama":     {"type": "openai", "base_url": "http://localhost:11434/v1",
                   "model": "qwen2.5-coder:14b"}
  }
}
```

Add any OpenAI-compatible service as a new entry (`type: "openai"` +
`base_url` + `api_key_env` + `model`). Local endpoints (localhost) don't need
a key. `type: "anthropic"` uses the native Anthropic API with adaptive
thinking, effort control and prompt caching.

Each provider entry can also set `"context_window": <tokens>` to override how
much context mini-cursor assumes that model has before it proactively
compacts history. Without it, mini-cursor guesses conservatively: 200k for
Anthropic, 128k for known hosted APIs (OpenAI, OpenRouter, Groq, ...), and a
cautious 8k for anything on localhost — local model servers commonly run with
a much smaller context than the underlying model supports unless configured
otherwise, so set this explicitly if you've raised `num_ctx` (Ollama) or
similar.

## Usage

```bash
minicursor ~/my-project              # interactive chat in that workspace
minicursor                           # current directory
minicursor -p "fix the failing test" # one-shot, non-interactive
minicursor --provider ollama         # pick a provider for this session
minicursor --model claude-sonnet-5 --effort xhigh
minicursor --yolo                    # auto-approve everything (careful!)
minicursor --no-checkpoints          # don't record file checkpoints (disables /undo)
```

### In-chat commands

| Command | Effect |
|---|---|
| `/help` | show help |
| `/clear` | reset the conversation |
| `/provider [name]` | list providers / switch (resets the chat) |
| `/model <id>` | switch model within the current provider |
| `/effort <lvl>` | `low` / `medium` / `high` / `xhigh` / `max` (Anthropic) |
| `/audit [path]` | offline security scan of the workspace (or a subpath) |
| `/yolo` | toggle confirmation prompts |
| `/undo` | revert the file changes from the last turn |
| `/checkpoints` | list recent undo checkpoints |
| `/compact` | summarize older history now to free up context |
| `/context` | show estimated context usage vs. the model's window |
| `/exit` or Ctrl+D | quit |

### Example session

```
you> add a --verbose flag to @cli.py
assistant
⚙ read_file {"path": "cli.py"}
⚙ edit_file {"path": "cli.py", "old_string": "...", "new_string": "..."}
╭─ changes to cli.py ──────────────────────────╮
│ -    parser.add_argument("--quiet", ...)     │
│ +    parser.add_argument("--verbose", ...)   │
╰──────────────────────────────────────────────╯
apply changes to cli.py? [y/N] y
Done — added the flag and wired it to the logger setup.
tokens: 8231 in / 412 out / 7100 cached
```

## Development

```bash
pip install -e ".[dev]"
pytest           # tools, agent loop and provider tests run offline
```

## Architecture

```
minicursor/
├── cli.py                    # REPL, slash commands, @mentions
├── agent.py                  # provider-agnostic agent loop + confirmations
├── tools.py                  # tool schemas + sandboxed executors
├── ui.py                     # rich rendering: streams, diffs, prompts
├── security.py               # offline security scanner (/audit + agent tool)
├── sca.py                    # dependency CVE check via OSV.dev
├── config.py                 # ~/.minicursor/config.json provider registry
├── compaction.py             # round-splitting + token-estimate helpers for /compact
├── checkpoints.py            # file-level undo store behind /undo, /checkpoints
└── providers/
    ├── base.py               # Backend interface (owns native msg format)
    ├── anthropic_backend.py  # Messages API: streaming, thinking, caching
    └── openai_backend.py     # any /v1/chat/completions endpoint
```

The agent loop is provider-agnostic: one streaming call per round; when the
model returns tool calls, mini-cursor executes them locally (asking you first
for anything mutating), sends results back and repeats until the turn ends.
Refusals, `pause_turn` and token-limit stops are handled explicitly.

Two pieces of session-level bookkeeping wrap that loop:

- **Compaction** (`compaction.py` + `Agent.maybe_compact`) splits the message
  history into "rounds" (a user turn plus everything the agent did in
  response), and — once the estimated context in use crosses ~80% of the
  model's context window minus the reserved output budget — asks the backend
  to summarize every round except the most recent `compact_keep_rounds` into
  one message. Each `Backend` implements `render_round` (native messages →
  plain text) and `complete_text` (one-shot, tool-free completion) to make
  this provider-agnostic; if the summarization call itself fails, mini-cursor
  logs it once and keeps working with the full history rather than looping on
  a broken call.
- **Checkpoints** (`checkpoints.py` + `Agent._checkpoint_before`) record each
  touched file's pre-turn content the first time `write_file`/`edit_file`
  touches it in a turn, and persist the whole turn as one checkpoint under
  `~/.minicursor/checkpoints/<hash of the workspace path>/`. `/undo` pops the
  most recent one and restores every file it touched.
