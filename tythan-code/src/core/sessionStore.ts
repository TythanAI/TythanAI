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
  title: string;
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

/** First user message, cleaned up, as the session's display title. */
export function titleFromTranscript(transcript: TranscriptEntry[]): string {
  const first = transcript.find((e) => e.kind === "user");
  if (!first) {
    return "(empty session)";
  }
  return first.text.split(/\s+/).filter(Boolean).join(" ").slice(0, 60) || "(empty session)";
}

export class SessionStore {
  constructor(readonly file: string) {}

  /** Load the stored session regardless of provider — the caller decides
   * whether the model history is usable (see `load`). */
  loadAny(): PersistedSession | undefined {
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
    if (typeof r.providerKey !== "string" || !Array.isArray(r.messages) || !Array.isArray(r.transcript)) {
      return undefined;
    }
    const transcript = r.transcript.map(sanitizeEntry).filter((e): e is TranscriptEntry => e !== null);
    return {
      providerKey: r.providerKey,
      messages: r.messages as NativeMessage[],
      transcript,
      savedAt: typeof r.savedAt === "number" ? r.savedAt : 0,
      title: typeof r.title === "string" ? r.title : titleFromTranscript(transcript),
    };
  }

  /** Load the stored session if it matches `providerKey`; undefined on any
   * mismatch, missing file, or corruption (never throws). */
  load(providerKey: string): PersistedSession | undefined {
    const session = this.loadAny();
    return session?.providerKey === providerKey ? session : undefined;
  }

  /** Persist the session. Empty sessions aren't worth a file (they'd litter
   * the session picker) and oversized ones are dropped — both clear instead.
   * Never throws. */
  save(providerKey: string, messages: NativeMessage[], transcript: TranscriptEntry[]): void {
    try {
      if (messages.length === 0 && transcript.length === 0) {
        this.clear();
        return;
      }
      const trimmed = transcript.slice(-MAX_TRANSCRIPT_ENTRIES).map((e) => ({
        ...e,
        text: e.text.slice(0, MAX_ENTRY_CHARS),
      }));
      const payload = JSON.stringify({
        providerKey,
        messages,
        transcript: trimmed,
        savedAt: Date.now() / 1000,
        title: titleFromTranscript(trimmed),
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

// -- multiple sessions per workspace ----------------------------------------

export const MAX_SESSIONS = 30;

export interface SessionMeta {
  id: string;
  title: string;
  providerKey: string;
  savedAt: number;
}

/** A directory of persisted sessions (one JSON file each) — the backing
 * store for the "Chat Sessions…" picker. */
export class SessionLibrary {
  constructor(readonly dir: string) {}

  newId(): string {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  store(id: string): SessionStore {
    // ids come from newId() or list(); strip anything path-like defensively.
    const safe = id.replace(/[^A-Za-z0-9_-]/g, "");
    return new SessionStore(path.join(this.dir, `${safe}.json`));
  }

  /** All stored sessions, most recently saved first. Corrupt files are
   * skipped. Also prunes beyond MAX_SESSIONS (oldest deleted). */
  list(): SessionMeta[] {
    let names: string[];
    try {
      names = fs.readdirSync(this.dir).filter((f) => f.endsWith(".json"));
    } catch {
      return [];
    }
    const out: SessionMeta[] = [];
    for (const name of names) {
      const id = name.slice(0, -".json".length);
      const session = this.store(id).loadAny();
      if (session) {
        out.push({ id, title: session.title, providerKey: session.providerKey, savedAt: session.savedAt });
      }
    }
    out.sort((a, b) => b.savedAt - a.savedAt);
    for (const stale of out.slice(MAX_SESSIONS)) {
      this.delete(stale.id);
    }
    return out.slice(0, MAX_SESSIONS);
  }

  delete(id: string): void {
    this.store(id).clear();
  }
}
