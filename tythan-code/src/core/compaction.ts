/**
 * Context-window compaction — provider-agnostic helpers for splitting the
 * flat message history into "rounds" and estimating its size when a backend
 * hasn't reported real token usage.
 */

// Rough fallback used only when a backend hasn't reported real token usage.
// Intentionally conservative-ish and provider-agnostic — good enough to
// trigger compaction before a hard context error, not an accounting-grade
// token count.
export const CHARS_PER_TOKEN_ESTIMATE = 4;

// Anthropic native message shape (content: string | content-block[]) and the
// OpenAI chat-completions shape (content: string | null, plus optional
// tool_calls / role: "tool") are both modeled loosely here — compaction only
// needs role + content shape, not the full native type.
export interface NativeMessage {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

/** True for a real user turn: `{ role: "user", content: "<string>" }`.
 *
 * Both backends append exactly this shape for real user input, and something
 * structurally different for tool results (Anthropic: role "user" but
 * array content; OpenAI: role "tool"). So this reliably marks the start of a
 * new round in either provider's native format without the caller needing to
 * know which provider produced the history.
 */
export function isRoundBoundary(message: NativeMessage): boolean {
  return message.role === "user" && typeof message.content === "string";
}

/** Group a flat message list into rounds, each starting at a user-turn boundary. */
export function splitIntoRounds(messages: NativeMessage[]): NativeMessage[][] {
  const rounds: NativeMessage[][] = [];
  for (const m of messages) {
    if (isRoundBoundary(m) || rounds.length === 0) {
      rounds.push([m]);
    } else {
      rounds[rounds.length - 1]?.push(m);
    }
  }
  return rounds;
}

/** Rough token estimate (~4 chars/token) for when real usage isn't known. */
export function estimateTokensHeuristic(messages: NativeMessage[], system = ""): number {
  let body: string;
  try {
    body = JSON.stringify(messages);
  } catch {
    body = String(messages);
  }
  return Math.floor(((body?.length ?? 0) + system.length) / CHARS_PER_TOKEN_ESTIMATE);
}

/** Keep the *tail* of `text` if it's over `limit` chars — used to bound how
 * much of a (potentially huge) old-rounds transcript is fed to the
 * summarization call. The tail is kept because the most recent old content
 * is the most likely to still be relevant. */
export function capHead(text: string, limit: number): string {
  if (text.length <= limit) {
    return text;
  }
  return `[earlier content omitted]\n...${text.slice(text.length - limit)}`;
}
