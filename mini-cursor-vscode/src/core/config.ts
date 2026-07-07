/**
 * Provider configuration and context-window defaults. Ported from the
 * Python mini-cursor CLI's config.py, including the fixes found during its
 * code review (explicit `=== undefined` checks rather than truthiness, so
 * an explicit contextWindow of 0 isn't silently discarded).
 */

export const DEFAULT_MODEL = "claude-opus-4-8";
export const DEFAULT_EFFORT = "high" as const;
export const DEFAULT_MAX_TOKENS = 8_192;

export const LOCAL_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"];

// Deliberately conservative guesses, not exact per-model figures — they only
// drive when mini-cursor proactively summarizes old history, so erring small
// (extra compaction) is far cheaper than erring large (a hard context-length
// error mid-turn). Override per provider with an explicit contextWindow.
export const DEFAULT_ANTHROPIC_CONTEXT_WINDOW = 200_000;
export const DEFAULT_LOCAL_CONTEXT_WINDOW = 8_000;
export const DEFAULT_GENERIC_CONTEXT_WINDOW = 32_000;

export const KNOWN_HOST_CONTEXT_WINDOWS: Record<string, number> = {
  "api.openai.com": 128_000,
  "openrouter.ai": 128_000,
  "api.groq.com": 128_000,
  "api.deepseek.com": 64_000,
  "api.mistral.ai": 128_000,
  "api.x.ai": 128_000,
};

export type ProviderType = "anthropic" | "openai";
export type EffortLevel = "low" | "medium" | "high" | "xhigh" | "max";

export interface ProviderConfig {
  name: string;
  type: ProviderType;
  model: string;
  baseUrl?: string;
  apiKey?: string;
  /** tokens; undefined means "use the type/host default" */
  contextWindow?: number;
}

export function defaultContextWindow(pcfg: ProviderConfig): number {
  if (pcfg.contextWindow !== undefined) {
    return pcfg.contextWindow;
  }
  if (pcfg.type === "anthropic") {
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW;
  }
  const baseUrl = pcfg.baseUrl ?? "";
  if (LOCAL_HOSTS.some((host) => baseUrl.includes(host))) {
    return DEFAULT_LOCAL_CONTEXT_WINDOW;
  }
  for (const [host, window] of Object.entries(KNOWN_HOST_CONTEXT_WINDOWS)) {
    if (baseUrl.includes(host)) {
      return window;
    }
  }
  return DEFAULT_GENERIC_CONTEXT_WINDOW;
}

export interface AgentConfig {
  workspaceRoot: string;
  effort: EffortLevel;
  maxTokens: number;
  yolo: boolean;
  checkpointsEnabled: boolean;
  compactKeepRounds: number;
}

export function defaultAgentConfig(workspaceRoot: string, overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    workspaceRoot,
    effort: DEFAULT_EFFORT,
    maxTokens: DEFAULT_MAX_TOKENS,
    yolo: false,
    checkpointsEnabled: true,
    compactKeepRounds: 2,
    ...overrides,
  };
}
