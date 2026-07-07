/**
 * Reads Tythan Code's settings from VS Code configuration + SecretStorage
 * and turns them into the plain config objects `core/` expects. This is the
 * only place that talks to `vscode.workspace.getConfiguration` for provider
 * settings, so the core agent stays fully decoupled from VS Code.
 */

import * as vscode from "vscode";

import type { AgentConfig, EffortLevel, ProviderConfig, ProviderType } from "../core/config";
import { defaultAgentConfig } from "../core/config";

const SECTION = "tythanCode";
const SECRET_PREFIX = "tythanCode.apiKey.";
const EFFORT_LEVELS: readonly EffortLevel[] = ["low", "medium", "high", "xhigh", "max"];

function providerTypeFor(provider: string): ProviderType {
  return provider === "anthropic" ? "anthropic" : "openai";
}

function defaultBaseUrlFor(provider: string): string | undefined {
  switch (provider) {
    case "openai":
      return "https://api.openai.com/v1";
    case "openrouter":
      return "https://openrouter.ai/api/v1";
    case "ollama":
      return "http://localhost:11434/v1";
    default:
      return undefined;
  }
}

/** Env vars users commonly already have set from using the CLI tools these
 * providers ship — checked as a convenience fallback if no key was stored
 * via the "Tythan Code: Set API Key" command. */
function envKeyFor(provider: string): string | undefined {
  switch (provider) {
    case "anthropic":
      return process.env.ANTHROPIC_API_KEY;
    case "openai":
      return process.env.OPENAI_API_KEY;
    case "openrouter":
      return process.env.OPENROUTER_API_KEY;
    default:
      return undefined;
  }
}

export async function resolveProviderConfig(context: vscode.ExtensionContext): Promise<ProviderConfig> {
  const cfg = vscode.workspace.getConfiguration(SECTION);
  const provider = cfg.get<string>("provider", "anthropic");
  const model = cfg.get<string>("model", "claude-opus-4-8");
  const contextWindow = cfg.get<number | null>("contextWindow", null);
  const customBaseUrl = cfg.get<string>("customBaseUrl", "").trim();
  const baseUrl = provider === "custom" ? customBaseUrl || undefined : (customBaseUrl || defaultBaseUrlFor(provider));

  const stored = await context.secrets.get(SECRET_PREFIX + provider);
  const apiKey = stored ?? envKeyFor(provider);

  return {
    name: provider,
    type: providerTypeFor(provider),
    model,
    baseUrl,
    apiKey,
    contextWindow: contextWindow ?? undefined,
  };
}

export function resolveAgentConfig(workspaceRoot: string): AgentConfig {
  const cfg = vscode.workspace.getConfiguration(SECTION);
  return defaultAgentConfig(workspaceRoot, {
    maxTokens: cfg.get<number>("maxOutputTokens", 8192),
    yolo: cfg.get<boolean>("yolo", false),
    checkpointsEnabled: cfg.get<boolean>("checkpointsEnabled", true),
    compactKeepRounds: cfg.get<number>("compactKeepRounds", 2),
  });
}

export function resolveEffort(): EffortLevel {
  const cfg = vscode.workspace.getConfiguration(SECTION);
  const raw = cfg.get<string>("effort", "high");
  return (EFFORT_LEVELS as readonly string[]).includes(raw) ? (raw as EffortLevel) : "high";
}

export function isInlineCompletionEnabled(): boolean {
  return vscode.workspace.getConfiguration(SECTION).get<boolean>("inlineCompletion.enabled", true);
}

export function inlineCompletionDebounceMs(): number {
  return vscode.workspace.getConfiguration(SECTION).get<number>("inlineCompletion.debounceMs", 400);
}

/** Optional dedicated (smaller/faster) model for inline tab-completion.
 * Empty means "use the main chat model". */
export function inlineCompletionModel(): string {
  return vscode.workspace.getConfiguration(SECTION).get<string>("inlineCompletion.model", "").trim();
}

export async function setApiKeyForProvider(context: vscode.ExtensionContext, provider: string, apiKey: string): Promise<void> {
  await context.secrets.store(SECRET_PREFIX + provider, apiKey);
}

export function currentProviderName(): string {
  return vscode.workspace.getConfiguration(SECTION).get<string>("provider", "anthropic");
}
