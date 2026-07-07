/**
 * The agent loop: stream a response, execute requested tools, repeat.
 *
 * Provider-agnostic: all model I/O goes through a Backend, which owns the
 * native message format. The agent owns tool execution, checkpoint
 * recording and context compaction. UI concerns (streaming text, showing
 * diffs, asking for confirmation) are injected via `AgentSink` /
 * `ToolApprover` so this whole module stays independent of `vscode` and is
 * fully unit-testable.
 *
 * Ported from the Python mini-cursor CLI's agent.py, carrying forward every
 * fix found reviewing it: the output-token reserve is capped at half the
 * context window (a small local model's window shouldn't have the full
 * default max-output-tokens subtracted from it), a disk error saving a
 * checkpoint can't mask a real in-flight exception, and the checkpoint label
 * is kept separate from whatever text is actually sent to the model.
 */

import type { AgentConfig } from "./config";
import { capHead, estimateTokensHeuristic, isRoundBoundary, splitIntoRounds } from "./compaction";
import type { NativeMessage } from "./compaction";
import { CheckpointStore } from "./checkpoints";
import type { Checkpoint } from "./checkpoints";
import { formatFindings, scanWorkspace } from "./security";
import { MAX_READ_LINES, MUTATING_TOOLS, TOOL_DEFINITIONS, ToolError, Workspace } from "./tools";
import type { Backend, ToolResultInput } from "./providers/types";

// Compact when the estimated context in use crosses this fraction of the
// token budget (context window minus the reserved output tokens).
export const COMPACT_TRIGGER_RATIO = 0.8;

// Floor for the token budget so a tiny/misconfigured context window can't
// make every single call trigger compaction.
export const MIN_TOKEN_BUDGET = 1000;

// Cap on how much of the old-rounds transcript is fed to the summarization call.
export const MAX_SUMMARY_INPUT_CHARS = 60_000;

export const SUMMARY_PROMPT = `Summarize the earlier part of this coding session so the assistant can keep \
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
facts and decisions, but don't pad it out.`;

export const SYSTEM_PROMPT = `You are Tythan Code, an AI coding assistant running inside the user's editor.
You operate on the user's project workspace via tools: read_file, write_file,
edit_file, list_files, search, run_command, security_scan.

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
  workspace. Lead with the outcome.`;

export interface AgentSink {
  assistantPrefix(): void;
  streamText(chunk: string): void;
  thinkingStarted(): void;
  flushStream(): void;
  toolCall(name: string, input: Record<string, unknown>): void;
  toolResult(output: string, isError: boolean): void;
  info(message: string): void;
  error(message: string): void;
}

export interface DiffPreview {
  path: string;
  before: string;
  after: string;
}

export interface ToolApprover {
  confirmDiff(preview: DiffPreview): Promise<boolean>;
  confirmCommand(command: string): Promise<boolean>;
}

function requireString(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  if (typeof value !== "string") {
    throw new ToolError(`Missing required parameter: ${key}`);
  }
  return value;
}

function optionalString(input: Record<string, unknown>, key: string, fallback: string): string {
  const value = input[key];
  return typeof value === "string" ? value : fallback;
}

function optionalNumber(input: Record<string, unknown>, key: string, fallback: number): number {
  const value = input[key];
  return typeof value === "number" ? value : fallback;
}

function optionalBoolean(input: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const value = input[key];
  return typeof value === "boolean" ? value : fallback;
}

export class Agent {
  readonly workspace: Workspace;
  readonly checkpoints: CheckpointStore;
  messages: NativeMessage[] = [];
  backend: Backend;

  // Once a compaction attempt fails (e.g. network error during the
  // summarization call), stop retrying it every tool round of the current
  // turn — the underlying call is likely to keep failing, and retrying
  // costs a real API round trip each time.
  private compactionUnavailable = false;

  constructor(
    private config: AgentConfig,
    private sink: AgentSink,
    private approver: ToolApprover,
    backend: Backend,
    checkpointStore: CheckpointStore,
  ) {
    this.workspace = new Workspace(config.workspaceRoot);
    this.backend = backend;
    this.checkpoints = checkpointStore;
  }

  reset(): void {
    this.messages = [];
  }

  /** Switch provider. History is provider-native, so the conversation resets. */
  setBackend(backend: Backend): void {
    this.backend = backend;
    this.reset();
  }

  systemPrompt(): string {
    return `${SYSTEM_PROMPT}\nWorkspace root: ${this.workspace.root}`;
  }

  /** Auto-approve every mutating tool call without asking. Dangerous — surfaced
   * as a getter/setter (rather than callers reaching into `config` directly)
   * so integration layers have a stable, public way to read and toggle it. */
  get yolo(): boolean {
    return this.config.yolo;
  }

  set yolo(value: boolean) {
    this.config.yolo = value;
  }

  get checkpointsEnabled(): boolean {
    return this.config.checkpointsEnabled;
  }

  // -- tool dispatch ---------------------------------------------------

  private async executeTool(name: string, toolInput: Record<string, unknown>): Promise<{ output: string; isError: boolean }> {
    const ws = this.workspace;
    try {
      if (MUTATING_TOOLS.has(name) && !(await this.approve(name, toolInput))) {
        return { output: "The user declined this action. Ask them how to proceed or try another approach.", isError: true };
      }
      switch (name) {
        case "read_file":
          return {
            output: ws.readFile(requireString(toolInput, "path"), optionalNumber(toolInput, "offset", 1), optionalNumber(toolInput, "limit", MAX_READ_LINES)),
            isError: false,
          };
        case "list_files":
          return { output: ws.listFiles(optionalString(toolInput, "pattern", "**/*")), isError: false };
        case "search":
          return {
            output: ws.search(requireString(toolInput, "pattern"), optionalString(toolInput, "glob", "**/*")),
            isError: false,
          };
        case "write_file": {
          const path = requireString(toolInput, "path");
          this.checkpointBefore(path);
          return { output: ws.writeFile(path, requireString(toolInput, "content")), isError: false };
        }
        case "edit_file": {
          const path = requireString(toolInput, "path");
          this.checkpointBefore(path);
          return {
            output: ws.editFile(
              path,
              requireString(toolInput, "old_string"),
              requireString(toolInput, "new_string"),
              optionalBoolean(toolInput, "replace_all", false),
            ),
            isError: false,
          };
        }
        case "security_scan": {
          const findings = scanWorkspace(ws, optionalString(toolInput, "path", "."));
          return { output: formatFindings(findings), isError: false };
        }
        case "run_command":
          return { output: await ws.runCommand(requireString(toolInput, "command")), isError: false };
        default:
          return { output: `Unknown tool: ${name}`, isError: true };
      }
    } catch (err) {
      if (err instanceof ToolError) {
        return { output: err.message, isError: true };
      }
      throw err;
    }
  }

  private async approve(name: string, toolInput: Record<string, unknown>): Promise<boolean> {
    if (this.config.yolo) {
      return true;
    }
    const ws = this.workspace;
    if (name === "write_file") {
      const path = requireString(toolInput, "path");
      const { old } = ws.prepareWrite(path);
      return this.approver.confirmDiff({ path, before: old, after: requireString(toolInput, "content") });
    }
    if (name === "edit_file") {
      const path = requireString(toolInput, "path");
      const { old, updated } = ws.prepareEdit(
        path,
        requireString(toolInput, "old_string"),
        requireString(toolInput, "new_string"),
        optionalBoolean(toolInput, "replace_all", false),
      );
      return this.approver.confirmDiff({ path, before: old, after: updated });
    }
    if (name === "run_command") {
      return this.approver.confirmCommand(requireString(toolInput, "command"));
    }
    return true;
  }

  private checkpointBefore(relPath: string): void {
    if (!this.config.checkpointsEnabled) {
      return;
    }
    let target: string;
    try {
      target = this.workspace.resolve(relPath);
    } catch {
      return;
    }
    try {
      this.checkpoints.recordBefore(target);
    } catch {
      // Never let checkpointing itself block or fail the actual tool call.
    }
  }

  // -- context compaction ------------------------------------------------

  /** Tokens available for context before the reserved output budget eats
   * into the model's context window. The reserve is capped at half the
   * context window: config.maxTokens is a global default sized for
   * large-context hosted models, but a small local model's contextWindow
   * can't sensibly reserve more output than that. */
  tokenBudget(): number {
    const reserve = Math.min(this.config.maxTokens, Math.floor(this.backend.contextWindow / 2));
    return Math.max(this.backend.contextWindow - reserve, MIN_TOKEN_BUDGET);
  }

  /** Best known estimate of the current history's size in tokens: the real
   * usage the backend reported after its last call, or a rough
   * character-based heuristic if that isn't available yet. */
  contextTokensEstimate(): number {
    if (this.backend.lastContextTokens !== undefined) {
      return this.backend.lastContextTokens;
    }
    return estimateTokensHeuristic(this.messages, this.systemPrompt());
  }

  /** Summarize older rounds into one message if the context is getting full
   * (or always, when `force=true`, e.g. from a manual "compact now" command).
   * Returns whether it actually compacted anything. */
  async maybeCompact(force = false): Promise<boolean> {
    if (!force) {
      if (this.compactionUnavailable) {
        return false;
      }
      if (this.contextTokensEstimate() < this.tokenBudget() * COMPACT_TRIGGER_RATIO) {
        return false;
      }
    }

    const rounds = splitIntoRounds(this.messages);
    const keep = Math.max(this.config.compactKeepRounds, 1);
    if (rounds.length <= keep) {
      return false; // nothing old enough to summarize yet
    }

    const toSummarize = rounds.slice(0, rounds.length - keep);
    const toKeep = rounds.slice(rounds.length - keep);

    let summary: string;
    try {
      const transcript = capHead(toSummarize.map((r) => this.backend.renderRound(r)).join("\n\n"), MAX_SUMMARY_INPUT_CHARS);
      summary = await this.backend.completeText(SUMMARY_PROMPT, transcript);
    } catch (err) {
      this.compactionUnavailable = true;
      this.sink.error(`context compaction unavailable (${(err as Error).message}); continuing with full history`);
      return false;
    }

    const flatKeep = toKeep.flat();
    const prefix = `[Summary of ${toSummarize.length} earlier turn(s), compacted to save context]\n${summary.trim()}\n[end summary]\n\n`;
    const first = flatKeep[0];
    if (first !== undefined && isRoundBoundary(first)) {
      flatKeep[0] = { ...first, content: prefix + (first.content as string) };
    } else {
      flatKeep.unshift({ role: "user", content: prefix.trim() });
    }

    const beforeCount = this.messages.length;
    this.messages = flatKeep;
    // Stale now that history changed shape; recomputed on the next real call.
    this.backend.lastContextTokens = undefined;
    this.sink.info(
      `context compacted: ${beforeCount} -> ${this.messages.length} message(s) (${toSummarize.length} earlier turn(s) summarized)`,
    );
    return true;
  }

  // -- the loop ----------------------------------------------------------

  /** Process one user message to completion (may involve many tool rounds).
   *
   * `label` is what gets recorded as this turn's checkpoint label; it
   * defaults to `userInput` but callers that expand @mentions before
   * calling runTurn should pass the raw, un-expanded text instead so the
   * label stays a readable summary of what the user typed.
   */
  async runTurn(userInput: string, label?: string): Promise<void> {
    this.backend.addUserMessage(this.messages, userInput);
    this.sink.assistantPrefix();
    this.checkpoints.beginTurn(label ?? userInput);
    this.compactionUnavailable = false;

    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        await this.maybeCompact();

        const result = await this.backend.streamTurn(this.messages, this.systemPrompt(), TOOL_DEFINITIONS, this.sink);

        if (result.stop === "refusal") {
          this.sink.error("The request was declined by the model's safety system. Try rephrasing.");
          return;
        }
        if (result.stop === "length") {
          this.sink.error("Response hit the output token limit; it may be incomplete.");
        }
        if (result.toolCalls.length === 0) {
          if (result.usage) {
            this.sink.info(`tokens: ${result.usage}`);
          }
          return;
        }

        const results: ToolResultInput[] = [];
        for (const call of result.toolCalls) {
          this.sink.toolCall(call.name, call.input);
          const { output, isError } = await this.executeTool(call.name, call.input);
          this.sink.toolResult(output, isError);
          results.push({ callId: call.id, output, isError });
        }
        this.backend.addToolResults(this.messages, results);
      }
    } finally {
      // A disk error here must never mask a real exception already
      // propagating from the try block above.
      let checkpoint: Checkpoint | undefined;
      try {
        checkpoint = this.checkpoints.commitTurn();
      } catch (err) {
        checkpoint = undefined;
        this.sink.error(`couldn't save checkpoint (${(err as Error).message}); this turn's edits won't be undoable`);
      }
      if (checkpoint) {
        const skipped = checkpoint.skippedLarge.length + checkpoint.skippedBinary.length;
        const note = skipped > 0 ? ` (${skipped} large/binary file(s) not covered)` : "";
        if (checkpoint.changes.length > 0) {
          this.sink.info(`checkpoint saved: ${checkpoint.changes.length} file(s) changed${note} — undo to revert`);
        } else {
          this.sink.info(`note: ${skipped} large/binary file(s) changed but aren't covered by undo`);
        }
      }
    }
  }
}
