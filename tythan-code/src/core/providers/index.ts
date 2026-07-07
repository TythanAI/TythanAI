import type { ProviderConfig } from "../config";
import { AnthropicBackend } from "./anthropicBackend";
import type { AnthropicAgentSettings } from "./anthropicBackend";
import { OpenAIBackend } from "./openaiBackend";
import { Backend, BackendConfigError } from "./types";

export function makeBackend(pcfg: ProviderConfig, anthropicSettings: AnthropicAgentSettings): Backend {
  if (pcfg.type === "anthropic") {
    return new AnthropicBackend(pcfg, anthropicSettings);
  }
  if (pcfg.type === "openai") {
    return new OpenAIBackend(pcfg);
  }
  throw new BackendConfigError(`unknown provider type: ${pcfg.type as string} (use "anthropic" or "openai")`);
}

export { Backend, BackendConfigError } from "./types";
export type { ToolCallRequest, ToolResultInput, TurnResult, StreamSink, StopReason } from "./types";
export { AnthropicBackend } from "./anthropicBackend";
export { OpenAIBackend } from "./openaiBackend";
