/**
 * Backend for any OpenAI-compatible chat-completions endpoint. Covers OpenAI
 * itself plus OpenRouter, Groq, DeepSeek, Mistral, xAI, and local servers
 * (Ollama, LM Studio, vLLM). Ported from the Python mini-cursor CLI's
 * openai_backend.py, including the fix found reviewing it: the
 * stream_options-support probe only treats a request-shape rejection
 * (BadRequestError / UnprocessableEntityError / TypeError) as "unsupported",
 * so an unrelated auth/rate-limit/network failure isn't misclassified and
 * doesn't permanently disable usage tracking.
 */

import OpenAI, { BadRequestError, UnprocessableEntityError } from "openai";
import type { ChatCompletionChunk, ChatCompletionMessageParam, ChatCompletionTool } from "openai/resources/chat/completions";

import { LOCAL_HOSTS, defaultContextWindow } from "../config";
import type { ProviderConfig } from "../config";
import type { NativeMessage } from "../compaction";
import { truncate } from "../tools";
import type { ToolDefinition } from "../tools";
import { BackendConfigError, Backend, makeTurnResult } from "./types";
import type { StreamSink, ToolCallRequest, ToolResultInput, TurnResult } from "./types";

export function toOpenAiTools(tools: ToolDefinition[]): ChatCompletionTool[] {
  return tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.inputSchema,
    },
  }));
}

export function resolveApiKey(pcfg: ProviderConfig): string {
  if (pcfg.apiKey) {
    return pcfg.apiKey;
  }
  if (pcfg.baseUrl && LOCAL_HOSTS.some((h) => pcfg.baseUrl?.includes(h))) {
    return "local"; // local servers don't check the key
  }
  throw new BackendConfigError(`provider '${pcfg.name}' needs an API key`);
}

interface PendingToolCall {
  id: string;
  name: string;
  args: string;
}

export class OpenAIBackend extends Backend {
  readonly name: string;
  private readonly client: OpenAI;
  /** undefined = untested, true/false = known from a prior call. Some
   * OpenAI-compatible endpoints (notably some local servers) reject the
   * stream_options parameter outright, so we probe once and remember. */
  private usageSupported: boolean | undefined = undefined;

  constructor(pcfg: ProviderConfig, client?: OpenAI) {
    super(pcfg.model, defaultContextWindow(pcfg));
    this.name = pcfg.name;
    this.client = client ?? new OpenAI({ baseURL: pcfg.baseUrl, apiKey: resolveApiKey(pcfg) });
  }

  addUserMessage(messages: NativeMessage[], text: string): void {
    messages.push({ role: "user", content: text });
  }

  addToolResults(messages: NativeMessage[], results: ToolResultInput[]): void {
    for (const r of results) {
      messages.push({ role: "tool", tool_call_id: r.callId, content: r.output });
    }
  }

  private async createStream(
    fullMessages: ChatCompletionMessageParam[],
    tools: ToolDefinition[],
  ): Promise<AsyncIterable<ChatCompletionChunk>> {
    const base = { model: this.model, messages: fullMessages, tools: toOpenAiTools(tools), stream: true as const };
    if (this.usageSupported === false) {
      return this.client.chat.completions.create(base);
    }
    try {
      const stream = await this.client.chat.completions.create({
        ...base,
        stream_options: { include_usage: true },
      });
      this.usageSupported = true;
      return stream;
    } catch (err) {
      if (err instanceof BadRequestError || err instanceof UnprocessableEntityError || err instanceof TypeError) {
        // These specifically mean "the request body/params were rejected" —
        // the closest thing to a reliable signal that stream_options isn't
        // recognized. Remember it and fall back so we don't pay for a failed
        // request every call. Anything else (auth, rate limit, network, 5xx)
        // is unrelated to stream_options support and must propagate normally
        // instead of permanently disabling usage tracking for an unrelated,
        // possibly transient reason.
        this.usageSupported = false;
        return this.client.chat.completions.create(base);
      }
      throw err;
    }
  }

  async streamTurn(
    messages: NativeMessage[],
    system: string,
    tools: ToolDefinition[],
    sink: StreamSink,
  ): Promise<TurnResult> {
    const fullMessages = [{ role: "system" as const, content: system }, ...messages] as ChatCompletionMessageParam[];
    const stream = await this.createStream(fullMessages, tools);

    const textParts: string[] = [];
    const pending = new Map<number, PendingToolCall>();
    let finishReason: string | null = null;

    for await (const chunk of stream) {
      if (chunk.usage) {
        const promptTokens = chunk.usage.prompt_tokens;
        if (promptTokens !== undefined) {
          this.lastContextTokens = promptTokens;
        }
      }
      const choice = chunk.choices?.[0];
      if (!choice) {
        continue;
      }
      const delta = choice.delta;
      if (delta?.content) {
        textParts.push(delta.content);
        sink.streamText(delta.content);
      }
      if (delta?.tool_calls) {
        for (const tc of delta.tool_calls) {
          const slot = pending.get(tc.index) ?? { id: "", name: "", args: "" };
          if (tc.id) {
            slot.id = tc.id;
          }
          if (tc.function?.name) {
            slot.name += tc.function.name;
          }
          if (tc.function?.arguments) {
            slot.args += tc.function.arguments;
          }
          pending.set(tc.index, slot);
        }
      }
      if (choice.finish_reason) {
        finishReason = choice.finish_reason;
      }
    }
    sink.flushStream();

    const assistant: NativeMessage = { role: "assistant", content: textParts.join("") || null };
    const calls: ToolCallRequest[] = [];
    if (pending.size > 0) {
      const toolCallsForHistory: unknown[] = [];
      for (const [index, slot] of [...pending.entries()].sort((a, b) => a[0] - b[0])) {
        const callId = slot.id || `call_${index}`;
        toolCallsForHistory.push({
          id: callId,
          type: "function",
          function: { name: slot.name, arguments: slot.args },
        });
        let parsed: Record<string, unknown> = {};
        try {
          parsed = slot.args.trim() ? (JSON.parse(slot.args) as Record<string, unknown>) : {};
        } catch {
          parsed = {};
        }
        calls.push({ id: callId, name: slot.name, input: parsed });
      }
      assistant.tool_calls = toolCallsForHistory;
    }
    messages.push(assistant);

    if (calls.length > 0) {
      return makeTurnResult("tool_use", calls);
    }
    if (finishReason === "length") {
      return makeTurnResult("length");
    }
    return makeTurnResult("end");
  }

  // -- context-compaction support ---------------------------------------

  override renderRound(roundMessages: NativeMessage[]): string {
    const lines: string[] = [];
    for (const m of roundMessages) {
      const role = m.role ?? "?";
      if (role === "tool") {
        lines.push(`tool result: ${truncate(String(m.content ?? ""), 1000)}`);
        continue;
      }
      const content = m.content;
      if (typeof content === "string" && content) {
        lines.push(`${role}: ${content}`);
      }
      const toolCalls = (m.tool_calls as Array<Record<string, unknown>> | undefined) ?? [];
      for (const call of toolCalls) {
        const fn = (call.function as Record<string, unknown> | undefined) ?? {};
        const args = truncate(String(fn.arguments ?? ""), 500);
        lines.push(`${role} called tool ${String(fn.name)}(${args})`);
      }
    }
    return lines.join("\n");
  }

  override async completeText(system: string, userText: string): Promise<string> {
    // Capped like AnthropicBackend.completeText — this is only ever used for
    // a compaction summary, so a verbose/non-compliant model can't return an
    // unbounded completion that defeats the point of compacting.
    const response = await this.client.chat.completions.create({
      model: this.model,
      max_tokens: 2000,
      messages: [
        { role: "system", content: system },
        { role: "user", content: userText },
      ],
    });
    return response.choices[0]?.message.content ?? "";
  }
}
