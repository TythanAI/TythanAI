/**
 * Chat session persistence: saves the provider-native message history plus a
 * plain display transcript to one JSON file per workspace, so closing VS
 * Code doesn't lose the conversation.
 *
 * The history is provider-native (Anthropic content blocks vs OpenAI chat
 * messages are not interchangeable), so a saved session is only restored
 * when the current provider+model matches the one it was recorded with —
 * otherwise it's silently discarded, same as switching providers mid-session.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import type { NativeMessage } from "./compaction";

export const MAX_TRANSCRIPT_ENTRIES = 300;
export const MAX_ENTRY_CHARS = 20_000;
// A session bigger than this isn't worth persisting — dropping it is better
// than multi-MB JSON parses on every activation.
export const MAX_SESSION_BYTES = 4_000_000;

export interface TranscriptEntry {
  kind: "user" | "assistant" | "info" | "error" | "toolCall" | "toolResult";
  text: string;
  /** tool name, for kind === "toolCall" */
  name?: string;
  /** for kind === "toolResult" */
  isError?: boolean;
}

export interface PersistedSession {
  providerKey: string;
  messages: NativeMessage[];
  transcript: TranscriptEntry[];
  savedAt: number;
}

function sanitizeEntry(raw: unknown): TranscriptEntry | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const r = raw as Record<string, unknown>;
  const kinds = ["user", "assistant", "info", "error", "toolCall", "toolResult"];
  if (typeof r.kind !== "string" || !kinds.includes(r.kind) || typeof r.text !== "string") {
    return null;
  }
  return {
    kind: r.kind as TranscriptEntry["kind"],
    text: r.text.slice(0, MAX_ENTRY_CHARS),
    name: typeof r.name === "string" ? r.name : undefined,
    isError: typeof r.isError === "boolean" ? r.isError : undefined,
  };
}

export class SessionStore {
  constructor(readonly file: string) {}

  /** Load the stored session if it matches `providerKey`; undefined on any
   * mismatch, missing file, or corruption (never throws). */
  load(providerKey: string): PersistedSession | undefined {
    let raw: unknown;
    try {
      const stat = fs.statSync(this.file);
      if (!stat.isFile() || stat.size > MAX_SESSION_BYTES) {
        return undefined;
      }
      raw = JSON.parse(fs.readFileSync(this.file, "utf-8"));
    } catch {
      return undefined;
    }
    if (typeof raw !== "object" || raw === null) {
      return undefined;
    }
    const r = raw as Record<string, unknown>;
    if (r.providerKey !== providerKey || !Array.isArray(r.messages) || !Array.isArray(r.transcript)) {
      return undefined;
    }
    const transcript = r.transcript.map(sanitizeEntry).filter((e): e is TranscriptEntry => e !== null);
    return {
      providerKey,
      messages: r.messages as NativeMessage[],
      transcript,
      savedAt: typeof r.savedAt === "number" ? r.savedAt : 0,
    };
  }

  /** Persist the session. Oversized sessions are dropped (with the file
   * cleared) rather than written. Never throws. */
  save(providerKey: string, messages: NativeMessage[], transcript: TranscriptEntry[]): void {
    try {
      const trimmed = transcript.slice(-MAX_TRANSCRIPT_ENTRIES).map((e) => ({
        ...e,
        text: e.text.slice(0, MAX_ENTRY_CHARS),
      }));
      const payload = JSON.stringify({
        providerKey,
        messages,
        transcript: trimmed,
        savedAt: Date.now() / 1000,
      });
      if (payload.length > MAX_SESSION_BYTES) {
        this.clear();
        return;
      }
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file, payload, "utf-8");
    } catch {
      // Persistence is best-effort; a failed save must never break a turn.
    }
  }

  clear(): void {
    try {
      fs.unlinkSync(this.file);
    } catch {
      // already gone
    }
  }
}
