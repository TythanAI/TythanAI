# mini-cursor for VS Code

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

- **Chat sidebar** — click the mini-cursor icon in the activity bar. Streams
  the model's answer live; shows tool calls and their results inline.
- **Agentic file edits with real diffs** — `write_file`/`edit_file` open VS
  Code's built-in diff editor (before vs. proposed after) and ask you to
  confirm before anything is written. `run_command` asks before running,
  too.
- **Undo (`mini-cursor: Undo Last Agent Change`)** — every agent-authored
  file change is checkpointed before it happens. One command reverts a
  whole turn's file changes. Files over 5MB or that aren't valid UTF-8 are
  skipped rather than checkpointed (so undo never "restores" a corrupted
  copy) — you're told when that happens.
- **Automatic context compaction** — long sessions don't hit a hard
  context-length error. When the conversation approaches the model's context
  window, older turns get summarized into one message and the most recent
  turns are kept verbatim. `mini-cursor: Compact Context Now` / `mini-cursor:
  Show Context Usage` for manual control and visibility.
- **Built-in security scanner** — the same regex-based rule set as the CLI:
  leaked secrets/API keys, dangerous code patterns (`eval`, `pickle.loads`,
  SQL built from f-strings, `shell=True`, disabled TLS verification, weak
  ciphers, ...), insecure config (wildcard CORS, JWT `none`, `0.0.0.0`
  binds). Available to the agent as a tool and directly via `mini-cursor:
  Run Security Audit`.
- **Inline tab-completion** (ghost text) — see [Limitations](#limitations)
  below; this is real but slower than Copilot/Cursor's dedicated completion
  models.
- **Any model** — native Anthropic, or any OpenAI-compatible endpoint
  (OpenAI, OpenRouter, Groq, DeepSeek, local servers via Ollama/LM
  Studio/vLLM). API keys are stored with VS Code's `SecretStorage`, not in
  plaintext settings.
- **Workspace-confined** — every file tool resolves paths against the
  workspace root and rejects anything that escapes it, symlinks included.

## Install (from source — not yet published to the Marketplace)

```bash
cd mini-cursor-vscode
npm install
npm run build            # bundles src/extension.ts -> dist/extension.js
npm run package          # -> mini-cursor-0.1.0.vsix
code --install-extension mini-cursor-0.1.0.vsix
```

Or press `F5` in VS Code with this folder open to launch an Extension
Development Host with it loaded, no packaging needed.

Set an API key: run **mini-cursor: Set API Key for Provider** from the
Command Palette (stored via VS Code's SecretStorage — never written to
settings.json). If `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OPENROUTER_API_KEY`
is already set in your environment, mini-cursor picks that up automatically
as a fallback.

## Settings

| Setting | Default | Description |
|---|---|---|
| `miniCursor.provider` | `anthropic` | `anthropic` \| `openai` \| `openrouter` \| `ollama` \| `custom` |
| `miniCursor.model` | `claude-opus-4-8` | Model id for the active provider |
| `miniCursor.effort` | `high` | Reasoning effort (Anthropic only): low/medium/high/xhigh/max |
| `miniCursor.contextWindow` | _(auto)_ | Override the assumed context window in tokens |
| `miniCursor.customBaseUrl` | _(empty)_ | Base URL when provider is `custom` (or to override the default for `openai`/`openrouter`/`ollama`) |
| `miniCursor.maxOutputTokens` | `8192` | Max tokens reserved for a single response |
| `miniCursor.yolo` | `false` | Auto-approve every write/edit/command — **dangerous** |
| `miniCursor.checkpointsEnabled` | `true` | Record checkpoints for undo |
| `miniCursor.compactKeepRounds` | `2` | Turns kept verbatim when compacting |
| `miniCursor.inlineCompletion.enabled` | `true` | Show inline tab-completions |
| `miniCursor.inlineCompletion.debounceMs` | `400` | Delay after you stop typing before requesting a completion |

Local model context windows default conservatively (8k) since local servers
commonly run with a much smaller context than the underlying model supports
unless configured otherwise — set `miniCursor.contextWindow` explicitly if
you've raised it.

### Commands

All available from the Command Palette (`Cmd/Ctrl+Shift+P`):

- **mini-cursor: Open Chat**
- **mini-cursor: New Chat Session** — clears the conversation
- **mini-cursor: Undo Last Agent Change**
- **mini-cursor: Show Checkpoints**
- **mini-cursor: Compact Context Now**
- **mini-cursor: Show Context Usage**
- **mini-cursor: Run Security Audit**
- **mini-cursor: Toggle Auto-Approve (YOLO) Mode**
- **mini-cursor: Set API Key for Provider**
- **mini-cursor: Toggle Inline Tab-Completion**

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
  `write_file`/`edit_file`, which mini-cursor fully controls.
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
  - 131 unit tests pass (see [Testing](#testing)) covering every module
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

`npm test` runs 131 tests across 8 files, all offline (SDK clients are
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
  compaction triggering/failure handling, token-budget capping, and that a
  disk error saving a checkpoint can't mask a real in-flight exception.

## Architecture

```
mini-cursor-vscode/
├── src/
│   ├── extension.ts              # activation: the only file that wires vscode + core together
│   ├── core/                     # vscode-independent — fully unit tested
│   │   ├── agent.ts              # tool-execution loop, checkpoint + compaction wiring
│   │   ├── tools.ts              # workspace-confined file/shell tools
│   │   ├── checkpoints.ts        # file-level undo store
│   │   ├── compaction.ts         # round splitting, token heuristics
│   │   ├── security.ts           # regex-based security scanner
│   │   ├── config.ts             # provider config, context-window defaults
│   │   └── providers/            # Backend interface + Anthropic/OpenAI-compatible implementations
│   └── vscode-integration/       # thin adapters — the only files that import `vscode`
│       ├── settings.ts           # reads configuration + SecretStorage
│       ├── approver.ts           # diff editor + modal confirm for mutating tools
│       ├── chatPanel.ts          # webview chat sidebar (implements AgentSink)
│       ├── inlineCompletion.ts   # InlineCompletionItemProvider
│       └── runTurnSafely.ts      # provider-aware error -> user-facing message
└── test/
    ├── core/                     # vitest — no vscode dependency, runs anywhere
    └── integration/               # @vscode/test-electron smoke test (not run in this environment)
```
