import { describe, expect, it } from "vitest";

import {
  capHead,
  estimateTokensHeuristic,
  isRoundBoundary,
  splitIntoRounds,
} from "../../src/core/compaction";

describe("isRoundBoundary", () => {
  it("is true for a plain user text message", () => {
    expect(isRoundBoundary({ role: "user", content: "hello" })).toBe(true);
  });

  it("is false for tool-result shapes", () => {
    // Anthropic tool_result: role "user" but array content, not a plain string.
    expect(
      isRoundBoundary({ role: "user", content: [{ type: "tool_result", tool_use_id: "x", content: "y" }] }),
    ).toBe(false);
    // OpenAI tool result: role "tool".
    expect(isRoundBoundary({ role: "tool", tool_call_id: "x", content: "y" })).toBe(false);
    // Assistant messages are never boundaries.
    expect(isRoundBoundary({ role: "assistant", content: "hi" })).toBe(false);
  });
});

describe("splitIntoRounds", () => {
  it("groups messages by user-turn boundary", () => {
    const messages = [
      { role: "user", content: "first" },
      { role: "assistant", content: "reply 1" },
      { role: "user", content: [{ type: "tool_result", content: "x" }] }, // not a boundary
      { role: "assistant", content: "reply 2" },
      { role: "user", content: "second" },
      { role: "assistant", content: "reply 3" },
    ];
    const rounds = splitIntoRounds(messages);
    expect(rounds).toHaveLength(2);
    expect(rounds[0]?.map((m) => m.content)).toEqual([
      "first",
      "reply 1",
      [{ type: "tool_result", content: "x" }],
      "reply 2",
    ]);
    expect(rounds[1]?.map((m) => m.content)).toEqual(["second", "reply 3"]);
  });

  it("returns an empty array for no messages", () => {
    expect(splitIntoRounds([])).toEqual([]);
  });

  it("keeps a leading non-boundary message rather than dropping it", () => {
    const messages = [{ role: "tool", tool_call_id: "x", content: "orphan" }];
    expect(splitIntoRounds(messages)).toEqual([messages]);
  });
});

describe("estimateTokensHeuristic", () => {
  it("grows with content length", () => {
    const small = estimateTokensHeuristic([{ role: "user", content: "hi" }]);
    const large = estimateTokensHeuristic([{ role: "user", content: "hi ".repeat(1000) }]);
    expect(large).toBeGreaterThan(small);
    expect(small).toBeGreaterThanOrEqual(0);
  });

  it("includes the system prompt length", () => {
    const messages = [{ role: "user", content: "hi" }];
    const withoutSystem = estimateTokensHeuristic(messages, "");
    const withSystem = estimateTokensHeuristic(messages, "x".repeat(4000));
    expect(withSystem).toBeGreaterThan(withoutSystem);
  });

  it("handles content that JSON.stringify can't fully serialize without throwing", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    const messages = [{ role: "assistant", content: [circular] }];
    expect(() => estimateTokensHeuristic(messages)).not.toThrow();
  });
});

describe("capHead", () => {
  it("leaves short text unchanged", () => {
    expect(capHead("short", 100)).toBe("short");
  });

  it("truncates from the front, keeping the tail", () => {
    const text = "0123456789".repeat(10); // 100 chars
    const capped = capHead(text, 20);
    expect(capped.endsWith(text.slice(-20))).toBe(true);
    expect(capped).toContain("[earlier content omitted]");
    expect(capped.length).toBeLessThan(text.length);
  });
});
