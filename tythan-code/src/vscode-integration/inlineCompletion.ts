/**
 * Inline tab-completion (ghost text), via VS Code's InlineCompletionItemProvider.
 *
 * Honest limitation: this calls the same general-purpose chat-completion
 * `completeText` used for context-compaction summaries, with a prompt asking
 * for a fill-in-the-middle style continuation — it is NOT a dedicated,
 * purpose-built low-latency FIM endpoint (the kind real production
 * tab-completion products use). Expect noticeably higher latency (roughly a
 * second or more per suggestion, provider/model dependent) than Copilot- or
 * Cursor-grade tab-complete. Debouncing keeps this from firing on every
 * keystroke, but it will never feel as instant as a dedicated small
 * completion model.
 */

import * as vscode from "vscode";

import type { Backend } from "../core/providers/types";
import { inlineCompletionDebounceMs, isInlineCompletionEnabled } from "./settings";

const CONTEXT_LINES = 200;

const FIM_SYSTEM_PROMPT = `You are a code completion engine embedded in an editor. You are given the \
code immediately before the cursor (PREFIX) and immediately after it (SUFFIX). \
Reply with ONLY the text that should be inserted at the cursor to continue the \
code naturally — no explanation, no markdown code fences, no repeating the \
prefix or suffix. If nothing sensible completes the code, reply with nothing.`;

function buildPrompt(languageId: string, prefix: string, suffix: string): string {
  return `Language: ${languageId}\n\n<PREFIX>\n${prefix}\n</PREFIX>\n<SUFFIX>\n${suffix}\n</SUFFIX>\n\nComplete at the cursor position (between PREFIX and SUFFIX).`;
}

/** Strips a wrapping \`\`\` fence if the model added one despite instructions not to. */
export function stripFence(text: string): string {
  const trimmed = text.trim();
  const fenced = /^```[^\n]*\n([\s\S]*?)\n?```$/.exec(trimmed);
  return (fenced ? fenced[1] : trimmed) ?? "";
}

export class TythanCodeInlineCompletionProvider implements vscode.InlineCompletionItemProvider {
  private debounceTimer: ReturnType<typeof setTimeout> | undefined;
  private debounceGeneration = 0;

  constructor(private readonly getBackend: () => Backend | undefined) {}

  async provideInlineCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
    _context: vscode.InlineCompletionContext,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlineCompletionItem[] | undefined> {
    if (!isInlineCompletionEnabled()) {
      return undefined;
    }
    const backend = this.getBackend();
    if (!backend) {
      return undefined;
    }

    const debounced = await this.debounce(inlineCompletionDebounceMs(), token);
    if (!debounced || token.isCancellationRequested) {
      return undefined;
    }

    const startLine = Math.max(0, position.line - CONTEXT_LINES);
    const endLine = Math.min(document.lineCount - 1, position.line + CONTEXT_LINES);
    const prefix = document.getText(new vscode.Range(new vscode.Position(startLine, 0), position));
    const suffix = document.getText(new vscode.Range(position, document.lineAt(endLine).range.end));

    let completion: string;
    try {
      completion = await backend.completeText(FIM_SYSTEM_PROMPT, buildPrompt(document.languageId, prefix, suffix));
    } catch {
      return undefined; // best-effort: never surface an error UI for a missed completion
    }
    if (token.isCancellationRequested) {
      return undefined;
    }

    const cleaned = stripFence(completion);
    if (!cleaned) {
      return undefined;
    }
    return [new vscode.InlineCompletionItem(cleaned, new vscode.Range(position, position))];
  }

  /** Resolves `true` once `ms` pass with no newer call superseding this one,
   * `false` if superseded or cancelled. Resolving (rather than leaving a
   * superseded call's promise pending forever) matters: VS Code cancels the
   * *previous* request's token when a new keystroke supersedes it, and
   * without a listener for that, the abandoned call's promise would never
   * settle at all. */
  private debounce(ms: number, token: vscode.CancellationToken): Promise<boolean> {
    const generation = ++this.debounceGeneration;
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    return new Promise((resolve) => {
      const cancelListener = token.onCancellationRequested(() => {
        cancelListener.dispose();
        resolve(false);
      });
      this.debounceTimer = setTimeout(() => {
        cancelListener.dispose();
        resolve(generation === this.debounceGeneration);
      }, ms);
    });
  }
}
