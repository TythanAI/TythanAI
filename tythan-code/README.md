# Tythan Code

**The AI coding agent that won't ship vulnerabilities — now inside your editor.**

A VS Code extension: chat with any model about your project from a sidebar,
let it read/edit files and run commands with your confirmation, see every
change as a real diff in VS Code's own diff editor, undo any turn's edits,
and get inline tab-completion as you type. Built on the same design as the
[mini-cursor terminal CLI](../mini-cursor) (`../mini-cursor` in this repo) —
same agent loop, same checkpoint/undo model, same context-compaction
algorithm, same security scanner — reimplemented natively in TypeScript so it
runs inside the VS Code extension host instead of shelling out to Python.

## Why an extension, not a VS Code fork

Cursor is a full fork of VS Code's source. Forking and maintaining that (a
multi-hundred-thousand-file codebase, its own Electron build pipeline, a
permanent rebase against upstream VS Code) is a different order of project —
not something that fits in one engineering pass, and not something a cloud
sandbox without a display or a VS Code binary can build and hand you a
working installer for. Everything that actually makes Cursor feel like
Cursor day to day — inline tab-completion, inline diffs, a chat sidebar,
agentic file edits — is achievable through VS Code's public Extension API,
which is what this does. (Continue.dev, Cline, and Roo Code — the serious
open-source "AI IDE" alternatives to Cursor — are all built the same way:
extensions, not forks.)

## Features

- **Chat sidebar** — click the Tythan Code icon in the activity bar (or
  `Ctrl+Alt+;`). Streams the model's answer live; shows tool calls and their
  results inline. Fenced code blocks render as real blocks with **Copy** and
  **Insert at cursor** buttons, and a **Stop** button aborts a generation
  mid-stream (history stays consistent — every started tool round is
  completed or cleanly skipped before the turn ends).
- **Composer (`Ctrl+Alt+I` / `Cmd+Alt+I`)** — Cursor's multi-file editing
  mode. Describe one task; the agent plans and edits as many files as
  needed, but every change is *staged* in memory (the agent can read its own
  staged edits back), nothing touches disk. At the end you get one checkbox
  list of every changed file — highlighting a file previews its diff, you
  uncheck what to skip, Enter applies the rest — recorded as one checkpoint,
  so a single Undo reverts the whole run. `run_command` is disabled in this
  mode on purpose: staged changes aren't on disk, so running tests would
  exercise the old code.
- **Fix problems with AI** — `Ctrl+Alt+.` sends the current file's
  errors/warnings (from whatever linters/language servers you run) to the
  agent, which fixes them through the normal confirmed-diff flow. Also a
  Quick Fix lightbulb ("Fix with Tythan Code") on any squiggle.
- **Chat sessions** — every conversation is kept per workspace;
  `Tythan Code: Chat Sessions…` switches between them (titles from your
  first message), New Chat Session starts a fresh one without losing the
  old, and sessions survive restarting VS Code.
- **Generate commit message** — the ✨ button in Source Control (or the
  command) reads the staged diff and writes a conventional-commits message
  straight into the commit box.
- **@codebase context** — mention `@codebase` in a chat message and Tythan
  Code retrieves the most relevant code chunks for your question (offline
  TF-IDF over identifier-aware tokens — `getUserProfile` matches "user
  profile") plus a project file map, and attaches them to the message. No
  index build step, and no code leaves your machine for indexing.
- **Persistent chat history** — the conversation (model history and rendered
  transcript) survives closing the sidebar *and* restarting VS Code, per
  workspace. The model-side history is only reattached when the
  provider+model still match; otherwise the transcript is shown and the
  model starts fresh.
- **Project rules files** — put instructions in `.tythanrules`,
  `.cursorrules` (existing Cursor projects keep working unchanged) or
  `AGENTS.md` at the workspace root and they're appended to the system
  prompt on every turn. Edits apply on the next message — no reload.
- **Inline edit (`Ctrl+Alt+K` / `Cmd+Alt+K`)** — the Cursor-style flow:
  select code (or just place the cursor), describe the change, review the
  proposed rewrite in VS Code's diff editor, apply with one click. Applied
  through the normal editor edit path, so plain editor undo reverts it.
- **Add selection to chat (`Ctrl+Alt+L` / `Cmd+Alt+L`)** — sends the selected
  lines (with file path and line numbers) into the chat input; with nothing
  selected it attaches the whole file as an `@file` mention. Both are also in
  the editor right-click menu.
- **Model switcher** — `Tythan Code: Select Model` quick-picks between known
  model ids for the active provider or any custom id, without opening
  settings.
- **Agentic file edits with real diffs** — `write_file`/`edit_file` open VS
  Code's built-in diff editor (before vs. proposed after) and ask you to
  confirm before anything is written. `run_command` asks before running,
  too.
- **Undo (`Tythan Code: Undo Last Agent Change`)** — every agent-authored
  file change is checkpointed before it happens. One command reverts a
  whole turn's file changes. Files over 5MB or that aren't valid UTF-8 are
  skipped rather than checkpointed (so undo never "restores" a corrupted
  copy) — you're told when that happens.
- **Automatic context compaction** — long sessions don't hit a hard
  context-length error. When the conversation approaches the model's context
  window, older turns get summarized into one message and the most recent
  turns are kept verbatim. `Tythan Code: Compact Context Now` / `Tythan Code:
  Show Context Usage` for manual control and visibility.
- **Built-in security scanner** — the same regex-based rule set as the CLI:
  leaked secrets/API keys, dangerous code patterns (`eval`, `pickle.loads`,
  SQL built from f-strings, `shell=True`, disabled TLS verification, weak
  ciphers, ...), insecure config (wildcard CORS, JWT `none`, `0.0.0.0`
  binds). Available to the agent as a tool and directly via `Tythan Code:
  Run Security Audit`.
- **Inline tab-completion** (ghost text) — with an LRU response cache
  (re-visiting the same spot answers instantly), a tight output cap, and an
  optional dedicated fast model: set `tythanCode.inlineCompletion.model` to
  a small model id (e.g. `claude-haiku-4-5-20251001`) to run completions on
  it while chat stays on the big model. Still not a purpose-built FIM
  endpoint — see [Limitations](#limitations).
- **Any model** — native Anthropic, or any OpenAI-compatible endpoint
  (OpenAI, OpenRouter, Groq, DeepSeek, local servers via Ollama/LM
  Studio/vLLM). API keys are stored with VS Code's `SecretStorage`, not in
  plaintext settings.
- **Workspace-confined** — every file tool resolves paths against the
  workspace root and rejects anything that escapes it, symlinks included.

## Install (from source — not yet published to the Marketplace)

```bash
cd tythan-code
npm install
npm run build            # bundles src/extension.ts -> dist/extension.js
npm run package          # -> tythan-code-0.4.0.vsix
code --install-extension tythan-code-0.4.0.vsix
```

Or press `F5` in VS Code with this folder open to launch an Extension
Development Host with it loaded, no packaging needed.

Set an API key: run **Tythan Code: Set API Key for Provider** from the
Command Palette (stored via VS Code's SecretStorage — never written to
settings.json). If `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OPENROUTER_API_KEY`
is already set in your environment, Tythan Code picks that up automatically
as a fallback.

## Settings

| Setting | Default | Description |
|---|---|---|
| `tythanCode.provider` | `anthropic` | `anthropic` \| `openai` \| `openrouter` \| `ollama` \| `custom` |
| `tythanCode.model` | `claude-opus-4-8` | Model id for the active provider |
| `tythanCode.effort` | `high` | Reasoning effort (Anthropic only): low/medium/high/xhigh/max |
| `tythanCode.contextWindow` | _(auto)_ | Override the assumed context window in tokens |
| `tythanCode.customBaseUrl` | _(empty)_ | Base URL when provider is `custom` (or to override the default for `openai`/`openrouter`/`ollama`) |
| `tythanCode.maxOutputTokens` | `8192` | Max tokens reserved for a single response |
| `tythanCode.yolo` | `false` | Auto-approve every write/edit/command — **dangerous** |
| `tythanCode.checkpointsEnabled` | `true` | Record checkpoints for undo |
| `tythanCode.compactKeepRounds` | `2` | Turns kept verbatim when compacting |
| `tythanCode.inlineCompletion.enabled` | `true` | Show inline tab-completions |
| `tythanCode.inlineCompletion.debounceMs` | `400` | Delay after you stop typing before requesting a completion |
| `tythanCode.inlineCompletion.model` | _(empty)_ | Dedicated fast model for tab-completion (empty = main chat model) |

Local model context windows default conservatively (8k) since local servers
commonly run with a much smaller context than the underlying model supports
unless configured otherwise — set `tythanCode.contextWindow` explicitly if
you've raised it.

### Commands

All available from the Command Palette (`Cmd/Ctrl+Shift+P`):

- **Tythan Code: Open Chat** (`Ctrl+Alt+;` / `Cmd+Alt+;`)
- **Tythan Code: New Chat Session** — starts a fresh conversation (the old one stays in Chat Sessions)
- **Tythan Code: Chat Sessions…** — switch between / delete saved conversations
- **Tythan Code: Stop Generation** — also a Stop button in the chat itself
- **Tythan Code: Composer (Multi-File Edit)** (`Ctrl+Alt+I` / `Cmd+Alt+I`)
- **Tythan Code: Edit Selection with AI** (`Ctrl+Alt+K` / `Cmd+Alt+K`)
- **Tythan Code: Add Selection to Chat** (`Ctrl+Alt+L` / `Cmd+Alt+L`)
- **Tythan Code: Fix Problems in Current File (AI)** (`Ctrl+Alt+.` / `Cmd+Alt+.`)
- **Tythan Code: Generate Commit Message** — also the ✨ button in Source Control
- **Tythan Code: Select Model**
- **Tythan Code: Undo Last Agent Change**
- **Tythan Code: Show Checkpoints**
- **Tythan Code: Compact Context Now**
- **Tythan Code: Show Context Usage**
- **Tythan Code: Run Security Audit**
- **Tythan Code: Toggle Auto-Approve (YOLO) Mode**
- **Tythan Code: Set API Key for Provider**
- **Tythan Code: Toggle Inline Tab-Completion**

## Limitations

Said plainly, because it matters more than it would in a marketing page:

- **Inline completion is not a dedicated FIM endpoint.** It reuses the same
  general chat-completion call used for context-compaction summaries, with a
  prompt asking for a fill-in-the-middle continuation. Real production
  tab-complete (Copilot, Cursor) uses small, purpose-built, low-latency
  completion models. This will typically take on the order of a second or
  more per suggestion, provider-dependent — useful, but not as snappy.
- **`run_command` isn't covered by undo.** There's no honest way to snapshot
  and revert an arbitrary shell command's effects. Checkpoints only cover
  `write_file`/`edit_file`, which Tythan Code fully controls.
- **No dependency-CVE (SCA) scanning.** The CLI's OSV.dev-backed dependency
  check (`sca.py`) wasn't ported in this pass — the security scanner here
  covers secrets/code-pattern/config rules only. Worth adding later; cut for
  scope, not silently dropped.
- **No live Extension-Development-Host test was run against this code.**
  The environment this was built in has no VS Code binary and its network
  policy blocks `update.code.visualstudio.com` (confirmed: a direct request
  returns HTTP 403 from the proxy), so `@vscode/test-electron` — which
  downloads a real VS Code build to run integration tests in — can't run
  here. What *was* verified in this environment:
  - `tsc --noEmit` passes with strict mode across every file, `core/` and
    `vscode-integration/` both.
  - `npm run build` (esbuild) bundles `dist/extension.js` cleanly.
  - `npm run package` (`vsce package`) produces a real, installable
    `.vsix` with no manifest warnings.
  - 191 unit tests pass (see [Testing](#testing)) covering every module
    under `core/` — the entire agent loop, both provider backends, tool
    execution and workspace confinement, checkpoints/undo, context
    compaction, and the security scanner.
  - What's *not* independently verified here: that the webview chat UI
    actually renders correctly, that VS Code's diff-editor/modal-dialog
    calls in `approver.ts` behave as expected end to end, or that inline
    completions actually appear as ghost text while typing. The
    `vscode-integration/` layer is thin, type-checked against
    `@types/vscode`, and structured so the only thing it does is marshal
    calls between real VS Code APIs and the tested `core/` logic — but "type
    checks" and "actually works when you press F5" are different claims,
    and only the first one is made here. A scaffolded integration smoke
    test (`test/integration/`) is included and ready to run — via
    `npm run test:integration` — on a machine with normal internet access.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit
npm test            # vitest — unit tests for everything under core/
npm run watch        # esbuild --watch, for iterating with F5
```

## Testing

`npm test` runs 191 tests across 12 files, all offline (SDK clients are
replaced with fakes matching the real `@anthropic-ai/sdk` / `openai` request
shapes — verified against the installed packages' type definitions, not
guessed):

- `tools.test.ts` — workspace confinement (including symlink resolution),
  glob matching, file read/write/edit, regex search, `@mention` expansion,
  and a real (short-timeout) test that a hung shell command's whole process
  *group* gets killed, not just the shell wrapping it.
- `compaction.test.ts` — round splitting, token-estimate heuristic, transcript capping.
- `checkpoints.test.ts` — recording, committing, undoing, retention pruning,
  the non-regular-file skip, the non-UTF-8 skip, and the symlink-introduced-
  after-checkpointing containment check.
- `security.test.ts` — every rule category, entropy detection, workspace scanning.
- `config.test.ts` — context-window defaults per provider/host.
- `anthropicBackend.test.ts` / `openaiBackend.test.ts` — streaming, tool-call
  extraction, usage tracking, the stream_options-support probe's narrowed
  error handling, transcript rendering, summarization.
- `agent.test.ts` — the full tool-execution loop, checkpoint wiring,
  compaction triggering/failure handling, token-budget capping, stop/abort
  semantics (a stopped turn still pairs every tool_use with a tool_result),
  tool-error containment, disabled tools, rules-file injection, and that a
  disk error saving a checkpoint can't mask a real in-flight exception.
- `changeset.test.ts` — composer staging: overlay reads/writes/edits, staged
  content visible to search/list, disk untouched, workspace confinement.
- `codebaseIndex.test.ts` — identifier tokenization, TF-IDF snippet ranking,
  file map, `@codebase` mention expansion.
- `rules.test.ts` — `.tythanrules`/`.cursorrules`/`AGENTS.md` precedence,
  truncation, empty-file fallthrough.
- `sessionStore.test.ts` — persistence round-trips, provider-mismatch
  discard, corruption tolerance, transcript/size caps.

## Architecture

```
tythan-code/
├── src/
│   ├── extension.ts              # activation: the only file that wires vscode + core together
│   ├── core/                     # vscode-independent — fully unit tested
│   │   ├── agent.ts              # tool-execution loop, checkpoint + compaction wiring
│   │   ├── tools.ts              # workspace-confined file/shell tools
│   │   ├── changeset.ts          # OverlayWorkspace: staged edits for composer mode
│   │   ├── checkpoints.ts        # file-level undo store
│   │   ├── codebaseIndex.ts      # offline @codebase retrieval (TF-IDF over identifier tokens)
│   │   ├── compaction.ts         # round splitting, token heuristics
│   │   ├── rules.ts              # .tythanrules/.cursorrules/AGENTS.md loading
│   │   ├── security.ts           # regex-based security scanner
│   │   ├── sessionStore.ts       # persistent chat sessions per workspace
│   │   ├── config.ts             # provider config, context-window defaults
│   │   └── providers/            # Backend interface + Anthropic/OpenAI-compatible implementations
│   └── vscode-integration/       # thin adapters — the only files that import `vscode`
│       ├── settings.ts           # reads configuration + SecretStorage
│       ├── approver.ts           # diff editor + modal confirm for mutating tools
│       ├── chatPanel.ts          # webview chat sidebar (implements AgentSink, keeps the transcript)
│       ├── composer.ts           # multi-file staged-edit flow + per-file review
│       ├── inlineCompletion.ts   # InlineCompletionItemProvider (+ LRU cache, fast-model support)
│       ├── inlineEdit.ts         # Ctrl+Alt+K edit-selection flow
│       └── runTurnSafely.ts      # provider-aware error -> user-facing message
└── test/
    ├── core/                     # vitest — no vscode dependency, runs anywhere
    └── integration/               # @vscode/test-electron smoke test (not run in this environment)
```
