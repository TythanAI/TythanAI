import OpenAI, { BadRequestError } from "openai";
import { describe, expect, it, vi } from "vitest";

import { OpenAIBackend, resolveApiKey, toOpenAiTools } from "../../src/core/providers/openaiBackend";
import { BackendConfigError } from "../../src/core/providers/types";
import { DEFAULT_LOCAL_CONTEXT_WINDOW } from "../../src/core/config";
import type { ProviderConfig } from "../../src/core/config";
import type { StreamSink } from "../../src/core/providers/types";
import { TOOL_DEFINITIONS } from "../../src/core/tools";

function pcfg(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return { name: "local", type: "openai", model: "m", baseUrl: "http://localhost:11434/v1", ...overrides };
}

function makeSink(): StreamSink & { texts: string[] } {
  return {
    texts: [],
    streamText(chunk: string) {
      this.texts.push(chunk);
    },
    thinkingStarted() {},
    flushStream() {},
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function makeFakeClient(createFn: (params: any) => unknown) {
  return { chat: { completions: { create: createFn } } } as unknown as OpenAI;
}

function makeBackend(client: OpenAI, overrides: Partial<ProviderConfig> = {}) {
  return new OpenAIBackend(pcfg(overrides), client);
}

describe("toOpenAiTools", () => {
  it("converts Tythan Code tool defs to OpenAI function-tool shape", () => {
    const tools = toOpenAiTools(TOOL_DEFINITIONS);
    expect(tools).toHaveLength(TOOL_DEFINITIONS.length);
    const read = tools.find((t) => t.type === "function" && t.function.name === "read_file");
    expect(read?.type).toBe("function");
    if (read?.type !== "function") {
      throw new Error("expected a function tool");
    }
    expect((read.function.parameters as { properties: Record<string, unknown> }).properties).toHaveProperty("path");
  });
});

describe("resolveApiKey", () => {
  it("uses the configured key when present", () => {
    expect(resolveApiKey(pcfg({ apiKey: "sk-123", baseUrl: "https://api.example.com/v1" }))).toBe("sk-123");
  });

  it("falls back to a dummy 'local' key for localhost endpoints", () => {
    expect(resolveApiKey(pcfg({ apiKey: undefined }))).toBe("local");
  });

  it("throws when a non-local endpoint has no key", () => {
    expect(() => resolveApiKey(pcfg({ apiKey: undefined, baseUrl: "https://api.example.com/v1" }))).toThrow(
      BackendConfigError,
    );
  });
});

describe("OpenAIBackend construction", () => {
  it("defaults to the conservative local context window", () => {
    const backend = makeBackend(makeFakeClient(async () => ({})));
    expect(backend.contextWindow).toBe(DEFAULT_LOCAL_CONTEXT_WINDOW);
  });
});

describe("OpenAIBackend stream_options probing", () => {
  it("uses stream_options when the endpoint accepts it", async () => {
    const calls: Record<string, unknown>[] = [];
    const createFn = vi.fn(async (params: Record<string, unknown>) => {
      calls.push(params);
      return (async function* () {})();
    });
    const backend = makeBackend(makeFakeClient(createFn));
    // @ts-expect-error calling a private method directly to test the probe in isolation
    await backend.createStream([{ role: "user", content: "hi" }], []);

    expect(calls).toHaveLength(1);
    expect(calls[0]?.stream_options).toEqual({ include_usage: true });
  });

  it("falls back and remembers when the endpoint rejects stream_options", async () => {
    const calls: Record<string, unknown>[] = [];
    const createFn = vi.fn(async (params: Record<string, unknown>) => {
      calls.push(params);
      if ("stream_options" in params) {
        throw new TypeError("unexpected keyword argument 'stream_options'");
      }
      return (async function* () {})();
    });
    const backend = makeBackend(makeFakeClient(createFn));

    // @ts-expect-error accessing the private method under test
    await backend.createStream([{ role: "user", content: "hi" }], []);
    expect(calls).toHaveLength(2);
    expect(calls[0]?.stream_options).toBeDefined();
    expect(calls[1]?.stream_options).toBeUndefined();

    // Remembered — no retry with stream_options on the next call.
    // @ts-expect-error accessing the private method under test
    await backend.createStream([{ role: "user", content: "hi" }], []);
    expect(calls).toHaveLength(3);
    expect(calls[2]?.stream_options).toBeUndefined();
  });

  it("does not misclassify an unrelated failure as 'unsupported'", async () => {
    const calls: Record<string, unknown>[] = [];
    const createFn = vi.fn(async (params: Record<string, unknown>) => {
      calls.push(params);
      throw new Error("network blip");
    });
    const backend = makeBackend(makeFakeClient(createFn));

    await expect(
      // @ts-expect-error accessing the private method under test
      backend.createStream([{ role: "user", content: "hi" }], []),
    ).rejects.toThrow("network blip");

    expect(calls).toHaveLength(1); // no silent fallback retry
    // @ts-expect-error reaching into private state
    expect(backend.usageSupported).toBeUndefined();
  });

  it("treats a real BadRequestError as 'unsupported'", async () => {
    const badRequest = new BadRequestError(400, undefined, "stream_options not supported", new Headers());
    let attempt = 0;
    const createFn = vi.fn(async () => {
      attempt++;
      if (attempt === 1) {
        throw badRequest;
      }
      return (async function* () {})();
    });
    const backend = makeBackend(makeFakeClient(createFn));
    // @ts-expect-error accessing the private method under test
    await backend.createStream([{ role: "user", content: "hi" }], []);
    // @ts-expect-error reaching into private state
    expect(backend.usageSupported).toBe(false);
  });
});

describe("OpenAIBackend.streamTurn", () => {
  it("captures prompt_tokens from the usage-only final chunk", async () => {
    async function* chunks() {
      yield { choices: [{ delta: { content: "hi" }, finish_reason: null }] };
      yield { choices: [{ delta: {}, finish_reason: "stop" }] };
      yield { choices: [], usage: { prompt_tokens: 4321 } };
    }
    const backend = makeBackend(makeFakeClient(async () => chunks()));
    const sink = makeSink();
    const result = await backend.streamTurn([], "system prompt", [], sink);

    expect(backend.lastContextTokens).toBe(4321);
    expect(result.stop).toBe("end");
    expect(sink.texts.join("")).toBe("hi");
  });

  it("extracts tool calls accumulated across chunks", async () => {
    async function* chunks() {
      yield {
        choices: [
          {
            delta: { tool_calls: [{ index: 0, id: "call_1", function: { name: "read_file", arguments: '{"pa' } }] },
            finish_reason: null,
          },
        ],
      };
      yield {
        choices: [
          {
            delta: { tool_calls: [{ index: 0, function: { arguments: 'th": "a.py"}' } }] },
            finish_reason: "tool_calls",
          },
        ],
      };
    }
    const backend = makeBackend(makeFakeClient(async () => chunks()));
    const result = await backend.streamTurn([], "sys", [], makeSink());
    expect(result.stop).toBe("tool_use");
    expect(result.toolCalls).toEqual([{ id: "call_1", name: "read_file", input: { path: "a.py" } }]);
  });

  it("reports 'length' on a length finish_reason with no tool calls", async () => {
    async function* chunks() {
      yield { choices: [{ delta: { content: "..." }, finish_reason: "length" }] };
    }
    const backend = makeBackend(makeFakeClient(async () => chunks()));
    const result = await backend.streamTurn([], "sys", [], makeSink());
    expect(result.stop).toBe("length");
  });
});

describe("OpenAIBackend.renderRound", () => {
  it("includes tool calls and tool results", () => {
    const backend = makeBackend(makeFakeClient(async () => ({})));
    const round = [
      { role: "user", content: "fix the bug" },
      {
        role: "assistant",
        content: null,
        tool_calls: [{ id: "c1", function: { name: "read_file", arguments: '{"path": "a.py"}' } }],
      },
      { role: "tool", tool_call_id: "c1", content: "file contents" },
      { role: "assistant", content: "fixed it" },
    ];
    const text = backend.renderRound(round);
    expect(text).toContain("user: fix the bug");
    expect(text).toContain("called tool read_file");
    expect(text).toContain("tool result: file contents");
    expect(text).toContain("fixed it");
  });
});

describe("OpenAIBackend.completeText", () => {
  it("caps output length like the Anthropic backend does", async () => {
    let captured: Record<string, unknown> = {};
    const createFn = vi.fn(async (params: Record<string, unknown>) => {
      captured = params;
      return { choices: [{ message: { content: "a summary" } }] };
    });
    const backend = makeBackend(makeFakeClient(createFn));
    const summary = await backend.completeText("sys", "old transcript");
    expect(summary).toBe("a summary");
    expect(captured.max_tokens).toBe(2000);
  });

  it("honors an explicit maxTokens override and passes the abort signal", async () => {
    const controller = new AbortController();
    let params: Record<string, unknown> = {};
    let options: { signal?: AbortSignal } | undefined;
    const createFn = vi.fn(async (p: Record<string, unknown>, o?: { signal?: AbortSignal }) => {
      params = p;
      options = o;
      return { choices: [{ message: { content: "ok" } }] };
    });
    const backend = makeBackend(makeFakeClient(createFn));
    await backend.completeText("sys", "text", { maxTokens: 9000, signal: controller.signal });
    expect(params.max_tokens).toBe(9000);
    expect(options?.signal).toBe(controller.signal);
  });
});

describe("OpenAIBackend.streamTurn abort signal", () => {
  it("hands the signal to chat.completions.create as a request option", async () => {
    const controller = new AbortController();
    const captured: Array<AbortSignal | undefined> = [];
    const createFn = vi.fn(async (_params: Record<string, unknown>, options?: { signal?: AbortSignal }) => {
      captured.push(options?.signal);
      return (async function* () {
        yield { choices: [{ delta: { content: "hi" }, finish_reason: "stop" }] };
      })();
    });
    const backend = makeBackend(makeFakeClient(createFn));
    await backend.streamTurn([], "sys", [], makeSink(), controller.signal);
    expect(captured).toEqual([controller.signal]);
  });
});
