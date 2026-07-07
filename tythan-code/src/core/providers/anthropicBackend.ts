/**
 * Native Anthropic Messages API backend (streaming, adaptive thinking,
 * prompt caching). Ported from the Python mini-cursor CLI's
 * anthropic_backend.py.
 */

import Anthropic from "@anthropic-ai/sdk";

import type { EffortLevel, ProviderConfig } from "../config";
import { defaultContextWindow } from "../config";
import type { NativeMessage } from "../compaction";
import type { ToolDefinition } from "../tools";
import { truncate } from "../tools";
import { Backend, makeTurnResult } from "./types";
import type { CompleteTextOptions, StreamSink, ToolCallRequest, ToolResultInput, TurnResult } from "./types";

function formatUsage(usage: Anthropic.Usage): string {
  const parts = [`${usage.input_tokens} in`, `${usage.output_tokens} out`];
  const cached = usage.cache_read_input_tokens ?? 0;
  if (cached) {
    parts.push(`${cached} cached`);
  }
  return parts.join(" / ");
}

/** Best estimate of how many tokens the *whole* sent context used up,
 * combining freshly-processed, cache-write and cache-read tokens. */
export function totalContextTokens(usage: Anthropic.Usage): number {
  return (usage.input_tokens ?? 0) + (usage.cache_read_input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0);
}

function toAnthropicTools(tools: ToolDefinition[]): Anthropic.Tool[] {
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.inputSchema as Anthropic.Tool.InputSchema,
  }));
}

export interface AnthropicAgentSettings {
  effort: EffortLevel;
  maxTokens: number;
}

export class AnthropicBackend extends Backend {
  readonly name: string;
  private readonly client: Anthropic;
  private readonly settings: AnthropicAgentSettings;

  constructor(pcfg: ProviderConfig, settings: AnthropicAgentSettings, client?: Anthropic) {
    super(pcfg.model, defaultContextWindow(pcfg));
    this.name = pcfg.name;
    this.settings = settings;
    this.client = client ?? new Anthropic({ apiKey: pcfg.apiKey, baseURL: pcfg.baseUrl });
  }

  addUserMessage(messages: NativeMessage[], text: string): void {
    messages.push({ role: "user", content: text });
  }

  addToolResults(messages: NativeMessage[], results: ToolResultInput[]): void {
    messages.push({
      role: "user",
      content: results.map((r) => ({
        type: "tool_result",
        tool_use_id: r.callId,
        content: r.output,
        is_error: r.isError,
      })),
    });
  }

  async streamTurn(
    messages: NativeMessage[],
    system: string,
    tools: ToolDefinition[],
    sink: StreamSink,
    signal?: AbortSignal,
  ): Promise<TurnResult> {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const stream = this.client.messages.stream(
        {
          model: this.model,
          max_tokens: this.settings.maxTokens,
          system: [{ type: "text", text: system, cache_control: { type: "ephemeral" } }],
          thinking: { type: "adaptive" },
          output_config: { effort: this.settings.effort },
          tools: toAnthropicTools(tools),
          messages: messages as unknown as Anthropic.MessageParam[],
        },
        { signal },
      );

      for await (const event of stream) {
        if (event.type === "content_block_start" && event.content_block.type === "thinking") {
          sink.thinkingStarted();
        } else if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
          sink.streamText(event.delta.text);
        }
      }
      sink.flushStream();
      const response = await stream.finalMessage();

      if (response.usage) {
        this.lastContextTokens = totalContextTokens(response.usage);
      }

      if (response.stop_reason === "refusal") {
        // Discard the (empty or partial) refused output; keep prior history.
        return makeTurnResult("refusal");
      }

      // Keep full content (incl. thinking/tool_use blocks) in history.
      messages.push({ role: "assistant", content: response.content });

      if (response.stop_reason === "pause_turn") {
        continue; // server-side pause; re-send to resume
      }

      const calls: ToolCallRequest[] = response.content
        .filter((b): b is Anthropic.ToolUseBlock => b.type === "tool_use")
        .map((b) => ({ id: b.id, name: b.name, input: b.input as Record<string, unknown> }));
      const usage = formatUsage(response.usage);
      if (calls.length > 0) {
        return makeTurnResult("tool_use", calls, usage);
      }
      if (response.stop_reason === "max_tokens") {
        return makeTurnResult("length", [], usage);
      }
      return makeTurnResult("end", [], usage);
    }
  }

  // -- context-compaction support ---------------------------------------

  override renderRound(roundMessages: NativeMessage[]): string {
    const lines: string[] = [];
    for (const m of roundMessages) {
      const role = m.role ?? "?";
      const content = m.content;
      if (typeof content === "string") {
        lines.push(`${role}: ${content}`);
        continue;
      }
      for (const block of (content as Array<Record<string, unknown>>) ?? []) {
        const btype = block?.type;
        if (btype === "text") {
          lines.push(`${role}: ${String(block.text ?? "")}`);
        } else if (btype === "tool_use") {
          const args = truncate(JSON.stringify(block.input ?? {}), 500);
          lines.push(`${role} called tool ${String(block.name)}(${args})`);
        } else if (btype === "tool_result") {
          const out = block.content;
          const text = typeof out === "string" ? out : JSON.stringify(out);
          lines.push(`tool result: ${truncate(text, 1000)}`);
        }
        // "thinking" blocks are internal reasoning — skip them in the summary transcript.
      }
    }
    return lines.join("\n");
  }

  override async completeText(system: string, userText: string, options?: CompleteTextOptions): Promise<string> {
    const response = await this.client.messages.create(
      {
        model: this.model,
        max_tokens: options?.maxTokens ?? 2000,
        system,
        messages: [{ role: "user", content: userText }],
      },
      { signal: options?.signal },
    );
    return response.content
      .filter((b): b is Anthropic.TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("");
  }
}
