import type Anthropic from "@anthropic-ai/sdk";
import { describe, expect, it, vi } from "vitest";

import { AnthropicBackend, totalContextTokens } from "../../src/core/providers/anthropicBackend";
import { DEFAULT_ANTHROPIC_CONTEXT_WINDOW } from "../../src/core/config";
import type { ProviderConfig } from "../../src/core/config";
import type { NativeMessage } from "../../src/core/compaction";
import type { StreamSink } from "../../src/core/providers/types";

function pcfg(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return { name: "anthropic", type: "anthropic", model: "claude-x", ...overrides };
}

function makeSink(): StreamSink & { texts: string[]; thinkingCalls: number; flushed: number } {
  return {
    texts: [],
    thinkingCalls: 0,
    flushed: 0,
    streamText(chunk: string) {
      this.texts.push(chunk);
    },
    thinkingStarted() {
      this.thinkingCalls++;
    },
    flushStream() {
      this.flushed++;
    },
  };
}

class FakeMessageStream {
  constructor(
    private events: Array<{ type: string; content_block?: unknown; delta?: unknown }>,
    private final: unknown,
  ) {}
  async *[Symbol.asyncIterator]() {
    for (const e of this.events) {
      yield e;
    }
  }
  async finalMessage() {
    return this.final;
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function makeClient(streamImpl: (params: any) => FakeMessageStream, createImpl?: (params: any) => unknown) {
  return {
    messages: {
      stream: streamImpl,
      create: createImpl,
    },
  } as unknown as Anthropic;
}

function makeBackend(client: Anthropic, overrides: Partial<ProviderConfig> = {}) {
  return new AnthropicBackend(pcfg(overrides), { effort: "high", maxTokens: 8192 }, client);
}

describe("AnthropicBackend construction", () => {
  it("defaults to the anthropic context window", () => {
    const backend = makeBackend(makeClient(() => new FakeMessageStream([], {}) as never));
    expect(backend.contextWindow).toBe(DEFAULT_ANTHROPIC_CONTEXT_WINDOW);
  });
});

describe("totalContextTokens", () => {
  it("sums input, cache-read and cache-creation tokens", () => {
    expect(
      totalContextTokens({ input_tokens: 100, cache_read_input_tokens: 50, cache_creation_input_tokens: 25 } as Anthropic.Usage),
    ).toBe(175);
  });

  it("treats missing fields as zero", () => {
    expect(totalContextTokens({ input_tokens: 100 } as Anthropic.Usage)).toBe(100);
  });
});

describe("AnthropicBackend.streamTurn", () => {
  it("streams text and returns 'end' with no tool calls", async () => {
    const finalMessage = {
      content: [{ type: "text", text: "hello there" }],
      stop_reason: "end_turn",
      usage: { input_tokens: 10, output_tokens: 5 },
    };
    const client = makeClient(
      () =>
        new FakeMessageStream(
          [
            { type: "content_block_start", content_block: { type: "text" } },
            { type: "content_block_delta", delta: { type: "text_delta", text: "hello there" } },
          ],
          finalMessage,
        ),
    );
    const backend = makeBackend(client);
    const sink = makeSink();
    const messages: NativeMessage[] = [{ role: "user", content: "hi" }];

    const result = await backend.streamTurn(messages, "system prompt", [], sink);

    expect(result.stop).toBe("end");
    expect(sink.texts.join("")).toBe("hello there");
    expect(sink.flushed).toBe(1);
    expect(backend.lastContextTokens).toBe(10);
    expect(messages).toHaveLength(2);
    expect(messages[1]?.role).toBe("assistant");
  });

  it("reports thinking blocks to the sink", async () => {
    const client = makeClient(
      () =>
        new FakeMessageStream(
          [{ type: "content_block_start", content_block: { type: "thinking" } }],
          { content: [], stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 1 } },
        ),
    );
    const backend = makeBackend(client);
    const sink = makeSink();
    await backend.streamTurn([], "sys", [], sink);
    expect(sink.thinkingCalls).toBe(1);
  });

  it("extracts tool_use blocks as tool calls", async () => {
    const finalMessage = {
      content: [{ type: "tool_use", id: "tu_1", name: "read_file", input: { path: "a.py" } }],
      stop_reason: "tool_use",
      usage: { input_tokens: 1, output_tokens: 1 },
    };
    const client = makeClient(() => new FakeMessageStream([], finalMessage));
    const backend = makeBackend(client);
    const result = await backend.streamTurn([], "sys", [], makeSink());

    expect(result.stop).toBe("tool_use");
    expect(result.toolCalls).toEqual([{ id: "tu_1", name: "read_file", input: { path: "a.py" } }]);
  });

  it("returns 'refusal' and discards the partial response", async () => {
    const finalMessage = { content: [{ type: "text", text: "" }], stop_reason: "refusal", usage: { input_tokens: 1, output_tokens: 0 } };
    const client = makeClient(() => new FakeMessageStream([], finalMessage));
    const backend = makeBackend(client);
    const messages: NativeMessage[] = [];
    const result = await backend.streamTurn(messages, "sys", [], makeSink());

    expect(result.stop).toBe("refusal");
    expect(messages).toHaveLength(0); // never appended to history
  });

  it("returns 'length' on max_tokens with no tool calls", async () => {
    const finalMessage = { content: [{ type: "text", text: "..." }], stop_reason: "max_tokens", usage: { input_tokens: 1, output_tokens: 1 } };
    const client = makeClient(() => new FakeMessageStream([], finalMessage));
    const backend = makeBackend(client);
    const result = await backend.streamTurn([], "sys", [], makeSink());
    expect(result.stop).toBe("length");
  });

  it("resends automatically on pause_turn until a real stop reason arrives", async () => {
    const paused = { content: [{ type: "text", text: "part 1" }], stop_reason: "pause_turn", usage: { input_tokens: 1, output_tokens: 1 } };
    const done = { content: [{ type: "text", text: "part 2" }], stop_reason: "end_turn", usage: { input_tokens: 2, output_tokens: 2 } };
    let call = 0;
    const streamFn = vi.fn(() => {
      call++;
      return new FakeMessageStream([], call === 1 ? paused : done);
    });
    const backend = makeBackend(makeClient(streamFn));
    const messages: NativeMessage[] = [];
    const result = await backend.streamTurn(messages, "sys", [], makeSink());

    expect(streamFn).toHaveBeenCalledTimes(2);
    expect(result.stop).toBe("end");
    // Both the paused and the final assistant message end up in history.
    expect(messages).toHaveLength(2);
  });
});

describe("AnthropicBackend.renderRound", () => {
  it("mixes text, tool_use and tool_result and skips thinking blocks", () => {
    const backend = makeBackend(makeClient(() => new FakeMessageStream([], {})));
    const round = [
      { role: "user", content: "please fix the bug" },
      {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "secret reasoning" },
          { type: "text", text: "Let me look" },
          { type: "tool_use", name: "read_file", input: { path: "a.py" } },
        ],
      },
      { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "file contents" }] },
    ];
    const text = backend.renderRound(round);
    expect(text).toContain("user: please fix the bug");
    expect(text).toContain("Let me look");
    expect(text).not.toContain("secret reasoning");
    expect(text).toContain("called tool read_file");
    expect(text).toContain("tool result: file contents");
  });
});

describe("AnthropicBackend.completeText", () => {
  it("joins text blocks from a non-streaming response", async () => {
    const createFn = vi.fn(async (params: { system: string }) => {
      expect(params.system).toBe("summarize this");
      return { content: [{ type: "text", text: "the summary" }] };
    });
    const backend = makeBackend(makeClient(() => new FakeMessageStream([], {}), createFn));
    const summary = await backend.completeText("summarize this", "old transcript");
    expect(summary).toBe("the summary");
  });

  it("ignores non-text blocks", async () => {
    const createFn = vi.fn(async () => ({
      content: [
        { type: "thinking", thinking: "internal" },
        { type: "text", text: "visible" },
      ],
    }));
    const backend = makeBackend(makeClient(() => new FakeMessageStream([], {}), createFn));
    expect(await backend.completeText("sys", "text")).toBe("visible");
  });
});
