/**
 * Backend interface shared by all providers. A Backend owns the wire format
 * of the conversation history: the agent keeps a plain array and only
 * manipulates it through the backend, so each provider can store messages in
 * its native shape (Anthropic content blocks vs OpenAI chat messages).
 * Switching providers therefore resets the conversation.
 */

import { DEFAULT_GENERIC_CONTEXT_WINDOW } from "../config";
import { truncate } from "../tools";
import type { ToolDefinition } from "../tools";
import type { NativeMessage } from "../compaction";

export class BackendConfigError extends Error {}

export interface ToolCallRequest {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultInput {
  callId: string;
  output: string;
  isError: boolean;
}

export type StopReason = "tool_use" | "end" | "refusal" | "length";

export interface TurnResult {
  stop: StopReason;
  toolCalls: ToolCallRequest[];
  /** human-readable token usage, may be empty */
  usage: string;
}

export function makeTurnResult(stop: StopReason, toolCalls: ToolCallRequest[] = [], usage = ""): TurnResult {
  return { stop, toolCalls, usage };
}

/** Sink the backend streams partial output into as a turn is generated. */
export interface StreamSink {
  streamText(chunk: string): void;
  thinkingStarted(): void;
  flushStream(): void;
}

export abstract class Backend {
  abstract readonly name: string;
  model: string;
  contextWindow: number;
  /** Real input-token count for the history as of the last streamTurn call,
   * when the provider reported one. undefined until a call has completed, or
   * if the provider never reports usage — callers fall back to a heuristic. */
  lastContextTokens: number | undefined = undefined;

  protected constructor(model: string, contextWindow: number = DEFAULT_GENERIC_CONTEXT_WINDOW) {
    this.model = model;
    this.contextWindow = contextWindow;
  }

  describe(): string {
    return `${this.name} / ${this.model}`;
  }

  abstract addUserMessage(messages: NativeMessage[], text: string): void;
  abstract addToolResults(messages: NativeMessage[], results: ToolResultInput[]): void;

  /** Make one model call: stream text to the sink, append the assistant
   * message(s) to `messages` in native format, and report tool calls. */
  abstract streamTurn(
    messages: NativeMessage[],
    system: string,
    tools: ToolDefinition[],
    sink: StreamSink,
  ): Promise<TurnResult>;

  // -- context-compaction support ---------------------------------------

  /** Best-effort plain-text rendering of one round of native messages, used
   * to build the transcript fed to `completeText` when summarizing old
   * history. Subclasses override this for a nicer, format-aware rendering;
   * this generic fallback just stringifies everything. */
  renderRound(roundMessages: NativeMessage[]): string {
    const lines: string[] = [];
    for (const m of roundMessages) {
      const role = m.role ?? "?";
      if (typeof m.content === "string") {
        lines.push(`${role}: ${m.content}`);
      } else {
        lines.push(`${role}: ${truncate(JSON.stringify(m.content), 2000)}`);
      }
    }
    return lines.join("\n");
  }

  /** One-shot, tool-free completion — used to generate a summary of old
   * history during compaction. Must be overridden by any backend that wants
   * to support compaction. */
  async completeText(_system: string, _userText: string): Promise<string> {
    throw new Error(`${this.name} backend does not support context summarization`);
  }
}
