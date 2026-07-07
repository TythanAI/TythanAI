import { describe, expect, it } from "vitest";

import {
  DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
  DEFAULT_GENERIC_CONTEXT_WINDOW,
  DEFAULT_LOCAL_CONTEXT_WINDOW,
  defaultAgentConfig,
  defaultContextWindow,
} from "../../src/core/config";
import type { ProviderConfig } from "../../src/core/config";

function pcfg(overrides: Partial<ProviderConfig>): ProviderConfig {
  return { name: "x", type: "openai", model: "m", ...overrides };
}

describe("defaultContextWindow", () => {
  it("honors an explicit override, including 0", () => {
    expect(defaultContextWindow(pcfg({ contextWindow: 9999 }))).toBe(9999);
    expect(defaultContextWindow(pcfg({ contextWindow: 0 }))).toBe(0);
  });

  it("defaults anthropic providers to the large context window", () => {
    expect(defaultContextWindow(pcfg({ type: "anthropic" }))).toBe(DEFAULT_ANTHROPIC_CONTEXT_WINDOW);
  });

  it("is conservative for a local base URL", () => {
    expect(defaultContextWindow(pcfg({ baseUrl: "http://localhost:11434/v1" }))).toBe(DEFAULT_LOCAL_CONTEXT_WINDOW);
  });

  it("recognizes known hosted providers", () => {
    expect(defaultContextWindow(pcfg({ baseUrl: "https://api.openai.com/v1" }))).toBe(128_000);
  });

  it("falls back to the generic default for an unknown host", () => {
    expect(defaultContextWindow(pcfg({ baseUrl: "https://example.com/v1" }))).toBe(DEFAULT_GENERIC_CONTEXT_WINDOW);
  });
});

describe("defaultAgentConfig", () => {
  it("fills in sensible defaults", () => {
    const cfg = defaultAgentConfig("/tmp/workspace");
    expect(cfg.workspaceRoot).toBe("/tmp/workspace");
    expect(cfg.yolo).toBe(false);
    expect(cfg.checkpointsEnabled).toBe(true);
    expect(cfg.compactKeepRounds).toBe(2);
  });

  it("lets overrides win", () => {
    const cfg = defaultAgentConfig("/tmp/workspace", { yolo: true, maxTokens: 123 });
    expect(cfg.yolo).toBe(true);
    expect(cfg.maxTokens).toBe(123);
  });
});
