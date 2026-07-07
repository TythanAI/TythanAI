import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Agent } from "../../src/core/agent";
import type { AgentSink, ToolApprover, DiffPreview } from "../../src/core/agent";
import { OverlayWorkspace } from "../../src/core/changeset";
import { CheckpointStore } from "../../src/core/checkpoints";
import { defaultAgentConfig } from "../../src/core/config";
import type { AgentConfig } from "../../src/core/config";
import { Backend, makeTurnResult } from "../../src/core/providers/types";
import type { StreamSink, ToolCallRequest, ToolResultInput, TurnResult } from "../../src/core/providers/types";
import type { NativeMessage } from "../../src/core/compaction";

class ScriptedBackend extends Backend {
  readonly name = "scripted";
  turns: TurnResult[];
  calls = 0;
  summaryCalls: string[] = [];
  summaryText: string;
  completeTextError: Error | undefined;

  constructor(turns: TurnResult[] = [], contextWindow = 32_000, summaryText = "SUMMARY") {
    super("fake-model", contextWindow);
    this.turns = [...turns];
    this.summaryText = summaryText;
  }

  addUserMessage(messages: NativeMessage[], text: string): void {
    messages.push({ role: "user", content: text });
  }

  addToolResults(messages: NativeMessage[], results: ToolResultInput[]): void {
    messages.push({ role: "tool_results", content: null, results });
  }

  async streamTurn(): Promise<TurnResult> {
    this.calls++;
    return this.turns.shift() ?? makeTurnResult("end");
  }

  override async completeText(_system: string, userText: string): Promise<string> {
    if (this.completeTextError) {
      throw this.completeTextError;
    }
    this.summaryCalls.push(userText);
    return this.summaryText;
  }
}

class FakeSink implements AgentSink {
  infos: string[] = [];
  errors: string[] = [];
  toolCalls: Array<{ name: string; input: Record<string, unknown> }> = [];
  toolResults: Array<{ output: string; isError: boolean }> = [];

  assistantPrefix(): void {}
  streamText(): void {}
  thinkingStarted(): void {}
  flushStream(): void {}
  toolCall(name: string, input: Record<string, unknown>): void {
    this.toolCalls.push({ name, input });
  }
  toolResult(output: string, isError: boolean): void {
    this.toolResults.push({ output, isError });
  }
  info(message: string): void {
    this.infos.push(message);
  }
  error(message: string): void {
    this.errors.push(message);
  }
}

class FakeApprover implements ToolApprover {
  approveDiffs: boolean;
  approveCommands: boolean;
  diffPreviews: DiffPreview[] = [];

  constructor(approveDiffs = true, approveCommands = true) {
    this.approveDiffs = approveDiffs;
    this.approveCommands = approveCommands;
  }

  async confirmDiff(preview: DiffPreview): Promise<boolean> {
    this.diffPreviews.push(preview);
    return this.approveDiffs;
  }

  async confirmCommand(): Promise<boolean> {
    return this.approveCommands;
  }
}

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-agent-"));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function makeAgent(
  backend: ScriptedBackend,
  configOverrides: Partial<AgentConfig> = {},
  approver: ToolApprover = new FakeApprover(),
): { agent: Agent; sink: FakeSink } {
  const config = defaultAgentConfig(tmpDir, { yolo: true, ...configOverrides });
  const sink = new FakeSink();
  const store = new CheckpointStore(tmpDir, path.join(tmpDir, ".checkpoints"));
  const agent = new Agent(config, sink, approver, backend, store);
  return { agent, sink };
}

describe("Agent tool round trip", () => {
  it("executes a read_file tool call and reports its result", async () => {
    fs.writeFileSync(path.join(tmpDir, "hello.txt"), "hi there\n");
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "read_file", input: { path: "hello.txt" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("what's in hello.txt?");

    expect(backend.calls).toBe(2);
    const toolMsg = agent.messages[1] as unknown as { role: string; results: ToolResultInput[] };
    expect(toolMsg.role).toBe("tool_results");
    expect(toolMsg.results[0]?.callId).toBe("tu_1");
    expect(toolMsg.results[0]?.output).toContain("hi there");
    expect(toolMsg.results[0]?.isError).toBe(false);
  });

  it("reports a tool error without crashing the turn", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "read_file", input: { path: "missing.txt" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("read missing.txt");

    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    expect(toolMsg.results[0]?.isError).toBe(true);
    expect(toolMsg.results[0]?.output).toMatch(/not found/);
  });

  it("ends the turn on refusal without executing any tools", async () => {
    const backend = new ScriptedBackend([makeTurnResult("refusal")]);
    const { agent, sink } = makeAgent(backend);
    await agent.runTurn("hello");
    expect(backend.calls).toBe(1);
    expect(agent.messages).toHaveLength(1);
    expect(sink.errors.length).toBeGreaterThan(0);
  });

  it("reports a declined write as an error tool result and doesn't write the file", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "data" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend, { yolo: false }, new FakeApprover(false));
    await agent.runTurn("create a.txt");

    expect(fs.existsSync(path.join(tmpDir, "a.txt"))).toBe(false);
    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    expect(toolMsg.results[0]?.isError).toBe(true);
    expect(toolMsg.results[0]?.output).toContain("declined");
  });

  it("resets history when the backend is switched", async () => {
    const backend = new ScriptedBackend([makeTurnResult("end")]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("hi");
    expect(agent.messages.length).toBeGreaterThan(0);
    agent.setBackend(new ScriptedBackend([makeTurnResult("end")]));
    expect(agent.messages).toEqual([]);
  });

  it("throws a Missing required parameter error instead of coercing undefined to a path", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "read_file", input: {} }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("read something");
    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    expect(toolMsg.results[0]?.isError).toBe(true);
    expect(toolMsg.results[0]?.output).toContain("Missing required parameter: path");
  });
});

describe("Agent tool-error containment", () => {
  it("returns an unexpected fs error as an error tool result instead of throwing", async () => {
    // "file.txt" is a regular file, so writing "file.txt/child.txt" makes
    // fs.mkdirSync throw a raw ENOTDIR — not a ToolError. That must come
    // back as an error *result*: the tool_use is already in history, and a
    // propagated throw would leave it without a matching tool_result,
    // wedging every subsequent Anthropic call in this conversation.
    fs.writeFileSync(path.join(tmpDir, "file.txt"), "i am a file");
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [
        { id: "tu_1", name: "write_file", input: { path: "file.txt/child.txt", content: "x" } },
      ]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);

    await expect(agent.runTurn("write into file.txt/child.txt")).resolves.toBeUndefined();

    expect(backend.calls).toBe(2); // the turn kept going after the failed tool
    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    expect(toolMsg.results[0]?.isError).toBe(true);
    expect(toolMsg.results[0]?.output).toContain("Tool failed unexpectedly");
  });
});

describe("Agent stop()", () => {
  it("skips remaining tool calls and ends the turn, keeping history consistent", async () => {
    fs.writeFileSync(path.join(tmpDir, "hello.txt"), "hi");
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [
        { id: "tu_1", name: "read_file", input: { path: "hello.txt" } },
        { id: "tu_2", name: "read_file", input: { path: "hello.txt" } },
      ]),
      makeTurnResult("end"),
    ]);
    const { agent, sink } = makeAgent(backend);
    const originalToolCall = sink.toolCall.bind(sink);
    sink.toolCall = (name, input) => {
      originalToolCall(name, input);
      agent.stop(); // user hits Stop while the round is executing
    };

    await agent.runTurn("read it twice");

    expect(backend.calls).toBe(1); // no further model call after the stop
    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    // Every requested tool_use still got a paired result, so the provider
    // conversation stays valid for the next turn.
    expect(toolMsg.results).toHaveLength(2);
    expect(toolMsg.results.every((r) => r.output.includes("Skipped"))).toBe(true);
    expect(sink.infos.some((m) => m.includes("generation stopped"))).toBe(true);
  });

  it("treats a stream error after stop() as a graceful stop, not a crash", async () => {
    class AbortThrowingBackend extends ScriptedBackend {
      agentRef: Agent | undefined;
      override async streamTurn(
        _messages?: unknown,
        _system?: unknown,
        _tools?: unknown,
        _sink?: unknown,
        signal?: AbortSignal,
      ): Promise<TurnResult> {
        this.calls++;
        this.agentRef?.stop();
        if (signal?.aborted) {
          throw new Error("Request was aborted.");
        }
        return makeTurnResult("end");
      }
    }
    const backend = new AbortThrowingBackend([]);
    const { agent, sink } = makeAgent(backend);
    backend.agentRef = agent;

    await expect(agent.runTurn("hello")).resolves.toBeUndefined();
    expect(sink.infos.some((m) => m.includes("generation stopped"))).toBe(true);
    expect(agent.running).toBe(false);
  });

  it("still propagates a real stream error when nothing was stopped", async () => {
    class ExplodingBackend extends ScriptedBackend {
      override async streamTurn(): Promise<TurnResult> {
        throw new Error("network down");
      }
    }
    const { agent } = makeAgent(new ExplodingBackend([]));
    await expect(agent.runTurn("hello")).rejects.toThrow("network down");
    expect(agent.running).toBe(false);
  });

  it("is a safe no-op when nothing is running", () => {
    const { agent } = makeAgent(new ScriptedBackend([]));
    expect(agent.running).toBe(false);
    expect(() => agent.stop()).not.toThrow();
  });
});

describe("Agent checkpoints", () => {
  it("creates an undoable checkpoint after write_file", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "v1" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("create a.txt");

    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("v1");
    const cps = agent.checkpoints.list();
    expect(cps).toHaveLength(1);
    expect(cps[0]?.changes[0]?.existedBefore).toBe(false);

    agent.checkpoints.undoLast();
    expect(fs.existsSync(path.join(tmpDir, "a.txt"))).toBe(false);
  });

  it("restores previous content after edit_file via undo", async () => {
    fs.writeFileSync(path.join(tmpDir, "a.txt"), "original");
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [
        { id: "tu_1", name: "edit_file", input: { path: "a.txt", old_string: "original", new_string: "changed" } },
      ]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("change a.txt");

    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("changed");
    agent.checkpoints.undoLast();
    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("original");
  });

  it("creates no checkpoint for a read-only turn", async () => {
    fs.writeFileSync(path.join(tmpDir, "hello.txt"), "hi");
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "read_file", input: { path: "hello.txt" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("what's in hello.txt?");
    expect(agent.checkpoints.list()).toEqual([]);
  });

  it("respects checkpointsEnabled=false", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "v1" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend, { checkpointsEnabled: false });
    await agent.runTurn("create a.txt");
    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("v1");
    expect(agent.checkpoints.list()).toEqual([]);
  });

  it("records a multi-file turn as a single checkpoint", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [
        { id: "tu_1", name: "write_file", input: { path: "a.txt", content: "a" } },
        { id: "tu_2", name: "write_file", input: { path: "b.txt", content: "b" } },
      ]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("create both files");

    const cps = agent.checkpoints.list();
    expect(cps).toHaveLength(1);
    expect(cps[0]?.changes.map((c) => c.path).sort()).toEqual(
      [path.join(tmpDir, "a.txt"), path.join(tmpDir, "b.txt")].sort(),
    );

    agent.checkpoints.undoLast();
    expect(fs.existsSync(path.join(tmpDir, "a.txt"))).toBe(false);
    expect(fs.existsSync(path.join(tmpDir, "b.txt"))).toBe(false);
  });
});

describe("Agent context compaction", () => {
  it("is a no-op when history is small", async () => {
    const backend = new ScriptedBackend([]);
    const { agent } = makeAgent(backend);
    agent.messages = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ];
    expect(await agent.maybeCompact()).toBe(false);
    expect(agent.messages).toHaveLength(2);
  });

  it("forced compaction summarizes old rounds and keeps the most recent", async () => {
    const backend = new ScriptedBackend([], 32_000, "the user asked X, we did Y");
    const { agent } = makeAgent(backend, { compactKeepRounds: 1 });
    for (let i = 0; i < 4; i++) {
      agent.messages.push({ role: "user", content: `turn ${i}` });
      agent.messages.push({ role: "assistant", content: `reply ${i}` });
    }

    const compacted = await agent.maybeCompact(true);

    expect(compacted).toBe(true);
    expect(backend.summaryCalls).toHaveLength(1);
    expect(agent.messages).toHaveLength(2);
    expect(agent.messages[0]?.content).toContain("the user asked X, we did Y");
    expect(agent.messages[0]?.content).toContain("turn 3");
    expect(agent.messages[1]?.content).toBe("reply 3");
  });

  it("never summarizes away the newest round", async () => {
    const backend = new ScriptedBackend([], 32_000, "summary");
    const { agent } = makeAgent(backend, { compactKeepRounds: 2 });
    for (let i = 0; i < 3; i++) {
      agent.messages.push({ role: "user", content: `turn ${i}` });
      agent.messages.push({ role: "assistant", content: `reply ${i}` });
    }
    await agent.maybeCompact(true);
    expect(agent.messages[agent.messages.length - 1]?.content).toBe("reply 2");
  });

  it("is a no-op (even forced) when there aren't enough rounds yet", async () => {
    const backend = new ScriptedBackend([]);
    const { agent } = makeAgent(backend, { compactKeepRounds: 5 });
    agent.messages = [
      { role: "user", content: "only one round" },
      { role: "assistant", content: "reply" },
    ];
    expect(await agent.maybeCompact(true)).toBe(false);
    expect(backend.summaryCalls).toHaveLength(0);
  });

  it("auto-triggers when estimated usage crosses the budget", async () => {
    const backend = new ScriptedBackend([], 1200, "compacted");
    const { agent } = makeAgent(backend, { maxTokens: 100, compactKeepRounds: 1 });
    for (let i = 0; i < 4; i++) {
      agent.messages.push({ role: "user", content: `turn ${i} ` + "x".repeat(2000) });
      agent.messages.push({ role: "assistant", content: `reply ${i}` });
    }
    expect(await agent.maybeCompact()).toBe(true);
    expect(backend.summaryCalls).toHaveLength(1);
  });

  it("uses real backend usage over the heuristic", async () => {
    const backend = new ScriptedBackend([], 1_000_000, "compacted");
    const { agent } = makeAgent(backend, { compactKeepRounds: 1 });
    for (let i = 0; i < 3; i++) {
      agent.messages.push({ role: "user", content: `tiny ${i}` });
      agent.messages.push({ role: "assistant", content: `ok ${i}` });
    }
    backend.lastContextTokens = 999_999;
    expect(agent.contextTokensEstimate()).toBe(999_999);
    expect(await agent.maybeCompact()).toBe(true); // would be false on the heuristic alone
  });

  it("reports a compaction failure without crashing and leaves history untouched", async () => {
    const backend = new ScriptedBackend([]);
    backend.completeTextError = new Error("network down");
    const { agent, sink } = makeAgent(backend, { compactKeepRounds: 1 });
    for (let i = 0; i < 3; i++) {
      agent.messages.push({ role: "user", content: `turn ${i}` });
      agent.messages.push({ role: "assistant", content: `reply ${i}` });
    }
    const before = [...agent.messages];

    const result = await agent.maybeCompact(true);

    expect(result).toBe(false);
    expect(agent.messages).toEqual(before);
    expect(sink.errors.some((e) => e.includes("compaction unavailable"))).toBe(true);
  });

  it("skips further compaction attempts in the same turn after a failure", async () => {
    const backend = new ScriptedBackend([makeTurnResult("end"), makeTurnResult("end")], 1200);
    backend.completeTextError = new Error("boom");
    const { agent } = makeAgent(backend, { maxTokens: 100, compactKeepRounds: 1 });
    for (let i = 0; i < 4; i++) {
      agent.messages.push({ role: "user", content: `turn ${i} ` + "x".repeat(2000) });
      agent.messages.push({ role: "assistant", content: `reply ${i}` });
    }
    expect(await agent.maybeCompact()).toBe(false);
    // @ts-expect-error reaching into private state
    expect(agent.compactionUnavailable).toBe(true);
    expect(await agent.maybeCompact()).toBe(false);
  });

  it("resets the compaction-unavailable flag at the start of each turn", async () => {
    const { agent } = makeAgent(new ScriptedBackend([makeTurnResult("end")]));
    // @ts-expect-error reaching into private state
    agent.compactionUnavailable = true;
    await agent.runTurn("hello");
    // @ts-expect-error reaching into private state
    expect(agent.compactionUnavailable).toBe(false);
  });
});

describe("Agent.tokenBudget", () => {
  it("caps the output reserve for a small local context window", () => {
    const { agent } = makeAgent(new ScriptedBackend([], 8_000));
    // reserve = min(8192 default maxTokens, 8000/2=4000) = 4000 -> budget = 4000
    expect(agent.tokenBudget()).toBe(4_000);
  });

  it("is unaffected for a large context window (no regression for the common case)", () => {
    const { agent } = makeAgent(new ScriptedBackend([], 200_000), { maxTokens: 64_000 });
    expect(agent.tokenBudget()).toBe(200_000 - 64_000);
  });
});

describe("Agent config extensions", () => {
  it("neither advertises nor executes disabled tools", async () => {
    let advertised: string[] = [];
    class ToolCapturingBackend extends ScriptedBackend {
      override async streamTurn(
        _messages?: unknown,
        _system?: unknown,
        tools?: Array<{ name: string }>,
        _sink?: unknown,
      ): Promise<TurnResult> {
        this.calls++;
        advertised = (tools ?? []).map((t) => t.name);
        return this.turns.shift() ?? makeTurnResult("end");
      }
    }
    const backend = new ToolCapturingBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "run_command", input: { command: "echo hi" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend, { disabledTools: ["run_command"] });
    await agent.runTurn("run something");

    expect(advertised).not.toContain("run_command");
    expect(advertised).toContain("read_file");
    const toolMsg = agent.messages[1] as unknown as { results: ToolResultInput[] };
    expect(toolMsg.results[0]?.isError).toBe(true);
    expect(toolMsg.results[0]?.output).toContain("not available");
  });

  it("appends systemPromptExtra to the system prompt", () => {
    const { agent } = makeAgent(new ScriptedBackend([]), { systemPromptExtra: "COMPOSER MODE ACTIVE" });
    expect(agent.systemPrompt()).toContain("COMPOSER MODE ACTIVE");
  });

  it("appends project rules from a .tythanrules file, fresh per call", () => {
    const { agent } = makeAgent(new ScriptedBackend([]));
    expect(agent.systemPrompt()).not.toContain("Project rules");
    fs.writeFileSync(path.join(tmpDir, ".tythanrules"), "Always write tests first.");
    const prompt = agent.systemPrompt();
    expect(prompt).toContain("Project rules (from .tythanrules");
    expect(prompt).toContain("Always write tests first.");
  });

  it("runs against an injected workspace (composer overlay wiring)", async () => {
    const overlay = new OverlayWorkspace(tmpDir);
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "staged" } }]),
      makeTurnResult("end"),
    ]);
    const config = defaultAgentConfig(tmpDir, { yolo: true, checkpointsEnabled: false });
    const sink = new FakeSink();
    const store = new CheckpointStore(tmpDir, path.join(tmpDir, ".checkpoints"));
    const agent = new Agent(config, sink, new FakeApprover(), backend, store, overlay);

    await agent.runTurn("stage a change");

    expect(fs.existsSync(path.join(tmpDir, "a.txt"))).toBe(false); // disk untouched
    expect(overlay.changes()).toHaveLength(1);
    expect(overlay.changes()[0]?.after).toBe("staged");
  });
});

describe("Agent checkpoint label", () => {
  it("uses an explicit label over the raw userInput passed to the model", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "v1" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    const expanded = '@notes.md summarize this\n\n<file path="notes.md">huge file contents...</file>';
    await agent.runTurn(expanded, "@notes.md summarize this");

    const cps = agent.checkpoints.list();
    expect(cps[0]?.label).toBe("@notes.md summarize this");
    expect(agent.messages[0]?.content).toBe(expanded);
  });

  it("defaults the label to userInput when none is given", async () => {
    const backend = new ScriptedBackend([
      makeTurnResult("tool_use", [{ id: "tu_1", name: "write_file", input: { path: "a.txt", content: "v1" } }]),
      makeTurnResult("end"),
    ]);
    const { agent } = makeAgent(backend);
    await agent.runTurn("create a.txt");
    expect(agent.checkpoints.list()[0]?.label).toBe("create a.txt");
  });
});

describe("Agent finally-block resilience", () => {
  it("survives commitTurn throwing without crashing runTurn", async () => {
    const { agent, sink } = makeAgent(new ScriptedBackend([makeTurnResult("end")]));
    agent.checkpoints.commitTurn = () => {
      throw new Error("disk full");
    };
    await expect(agent.runTurn("hello")).resolves.toBeUndefined();
    expect(sink.errors.some((e) => e.includes("disk full"))).toBe(true);
  });

  it("does not mask a real exception with a commitTurn error", async () => {
    class ExplodingBackend extends ScriptedBackend {
      override async streamTurn(): Promise<TurnResult> {
        throw new Error("network down");
      }
    }
    const { agent } = makeAgent(new ExplodingBackend([]));
    agent.checkpoints.commitTurn = () => {
      throw new Error("disk full");
    };
    await expect(agent.runTurn("hello")).rejects.toThrow("network down");
  });
});
