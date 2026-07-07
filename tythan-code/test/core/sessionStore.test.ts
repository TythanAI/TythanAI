import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MAX_TRANSCRIPT_ENTRIES, SessionStore } from "../../src/core/sessionStore";
import type { TranscriptEntry } from "../../src/core/sessionStore";

let tmpDir: string;
let store: SessionStore;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-session-"));
  store = new SessionStore(path.join(tmpDir, "nested", "session.json"));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

const transcript: TranscriptEntry[] = [
  { kind: "user", text: "hello" },
  { kind: "assistant", text: "hi there" },
  { kind: "toolCall", text: '{"path":"a.txt"}', name: "read_file" },
  { kind: "toolResult", text: "contents", isError: false },
];

describe("SessionStore", () => {
  it("round-trips messages and transcript (creating parent dirs)", () => {
    const messages = [
      { role: "user", content: "hello" },
      { role: "assistant", content: [{ type: "text", text: "hi there" }] },
    ];
    store.save("anthropic / claude-x", messages, transcript);

    const loaded = store.load("anthropic / claude-x");
    expect(loaded?.messages).toEqual(messages);
    expect(loaded?.transcript).toEqual(transcript);
    expect(loaded?.savedAt).toBeGreaterThan(0);
  });

  it("returns undefined for a provider/model mismatch", () => {
    store.save("anthropic / claude-x", [{ role: "user", content: "hi" }], transcript);
    expect(store.load("openai / gpt-x")).toBeUndefined();
    expect(store.load("anthropic / other-model")).toBeUndefined();
  });

  it("returns undefined for a missing file", () => {
    expect(store.load("anthropic / claude-x")).toBeUndefined();
  });

  it("survives a corrupt file without throwing", () => {
    fs.mkdirSync(path.dirname(store.file), { recursive: true });
    fs.writeFileSync(store.file, "{not json!!");
    expect(store.load("anthropic / claude-x")).toBeUndefined();
  });

  it("drops malformed transcript entries but keeps valid ones", () => {
    fs.mkdirSync(path.dirname(store.file), { recursive: true });
    fs.writeFileSync(
      store.file,
      JSON.stringify({
        providerKey: "k",
        messages: [],
        transcript: [{ kind: "user", text: "ok" }, { kind: "bogus", text: "x" }, "junk", { kind: "info" }],
        savedAt: 1,
      }),
    );
    const loaded = store.load("k");
    expect(loaded?.transcript).toEqual([{ kind: "user", text: "ok", name: undefined, isError: undefined }]);
  });

  it("caps the persisted transcript length", () => {
    const long: TranscriptEntry[] = Array.from({ length: MAX_TRANSCRIPT_ENTRIES + 50 }, (_, i) => ({
      kind: "info" as const,
      text: `entry ${i}`,
    }));
    store.save("k", [], long);
    const loaded = store.load("k");
    expect(loaded?.transcript).toHaveLength(MAX_TRANSCRIPT_ENTRIES);
    expect(loaded?.transcript[0]?.text).toBe("entry 50"); // oldest dropped
  });

  it("clears instead of writing an oversized session", () => {
    store.save("k", [], transcript);
    expect(fs.existsSync(store.file)).toBe(true);
    const huge = [{ role: "user", content: "x".repeat(5_000_000) }];
    store.save("k", huge, transcript);
    expect(fs.existsSync(store.file)).toBe(false);
  });

  it("clear() removes the file and is a no-op when absent", () => {
    store.save("k", [], transcript);
    store.clear();
    expect(fs.existsSync(store.file)).toBe(false);
    expect(() => store.clear()).not.toThrow();
  });
});
