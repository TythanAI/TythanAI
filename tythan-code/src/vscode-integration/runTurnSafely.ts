/**
 * Wraps Agent.runTurn with the same broad, provider-aware error handling the
 * Python CLI's run_turn_safely had: turn a raw SDK exception into a short,
 * actionable message instead of letting it bubble up as an unhandled
 * rejection and take down the extension host.
 */

import {
  APIConnectionError as AnthropicAPIConnectionError,
  APIError as AnthropicAPIError,
  AuthenticationError as AnthropicAuthenticationError,
  RateLimitError as AnthropicRateLimitError,
} from "@anthropic-ai/sdk";
import {
  APIConnectionError as OpenAIAPIConnectionError,
  APIError as OpenAIAPIError,
  AuthenticationError as OpenAIAuthenticationError,
  RateLimitError as OpenAIRateLimitError,
} from "openai";

import type { Agent, AgentSink } from "../core/agent";
import { expandCodebaseMention } from "../core/codebaseIndex";
import { expandMentions } from "../core/tools";

export async function runTurnSafely(agent: Agent, sink: AgentSink, text: string): Promise<void> {
  try {
    // Pass the raw text as the checkpoint label — the expansions below
    // inline file contents / retrieved snippets into what the model sees,
    // which would otherwise end up as unreadable noise in the checkpoints
    // list. @codebase retrieval uses the *raw* text as the query so terms
    // from already-attached files don't skew the ranking.
    let expanded = expandMentions(text, agent.workspace);
    expanded = expandCodebaseMention(expanded, agent.workspace, text);
    await agent.runTurn(expanded, text);
  } catch (err) {
    if (err instanceof AnthropicAuthenticationError || err instanceof OpenAIAuthenticationError) {
      sink.error('authentication failed — set your API key via "Tythan Code: Set API Key for Provider" and retry');
    } else if (err instanceof AnthropicRateLimitError || err instanceof OpenAIRateLimitError) {
      sink.error("rate limited — wait a moment and try again");
    } else if (err instanceof AnthropicAPIConnectionError || err instanceof OpenAIAPIConnectionError) {
      sink.error("network error — check your connection and try again");
    } else if (err instanceof AnthropicAPIError || err instanceof OpenAIAPIError) {
      sink.error(`API error ${err.status ?? ""}: ${err.message}`.trim());
    } else if (err instanceof Error) {
      sink.error(`${err.name || "Error"}: ${err.message}`);
    } else {
      sink.error(String(err));
    }
  }
}
