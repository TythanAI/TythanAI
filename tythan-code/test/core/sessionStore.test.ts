import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MAX_SESSIONS, MAX_TRANSCRIPT_ENTRIES, SessionLibrary, SessionStore, titleFromTranscript } from "../../src/core/sessionStore";
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

  it("does not persist an empty session (and clears any previous file)", () => {
    store.save("k", [], transcript);
    expect(fs.existsSync(store.file)).toBe(true);
    store.save("k", [], []);
    expect(fs.existsSync(store.file)).toBe(false);
  });

  it("loadAny() returns the session regardless of provider, with its title", () => {
    store.save("anthropic / claude-x", [{ role: "user", content: "hi" }], transcript);
    const loaded = store.loadAny();
    expect(loaded?.providerKey).toBe("anthropic / claude-x");
    expect(loaded?.title).toBe("hello");
  });
});

describe("titleFromTranscript", () => {
  it("uses the first user message, whitespace-collapsed and capped", () => {
    expect(titleFromTranscript([{ kind: "info", text: "x" }, { kind: "user", text: "  fix\n the   bug  " }])).toBe(
      "fix the bug",
    );
    expect(titleFromTranscript([{ kind: "user", text: "y".repeat(100) }])).toHaveLength(60);
  });

  it("falls back for transcripts with no user message", () => {
    expect(titleFromTranscript([])).toBe("(empty session)");
  });
});

describe("SessionLibrary", () => {
  it("lists sessions most recently saved first and loads them by id", () => {
    const library = new SessionLibrary(path.join(tmpDir, "lib"));
    const a = library.newId();
    const b = library.newId();
    library.store(a).save("k", [{ role: "user", content: "hi" }], [{ kind: "user", text: "first session" }]);
    library.store(b).save("k", [{ role: "user", content: "hi" }], [{ kind: "user", text: "second session" }]);
    // force distinct savedAt ordering
    const fileA = library.store(a).file;
    const olderPayload = JSON.parse(fs.readFileSync(fileA, "utf-8"));
    olderPayload.savedAt = olderPayload.savedAt - 100;
    fs.writeFileSync(fileA, JSON.stringify(olderPayload));

    const sessions = library.list();
    expect(sessions.map((s) => s.title)).toEqual(["second session", "first session"]);
    expect(library.store(sessions[0]!.id).loadAny()?.transcript[0]?.text).toBe("second session");
  });

  it("delete removes a session; corrupt files are skipped in list()", () => {
    const library = new SessionLibrary(path.join(tmpDir, "lib2"));
    const id = library.newId();
    library.store(id).save("k", [{ role: "user", content: "hi" }], [{ kind: "user", text: "bye" }]);
    fs.writeFileSync(path.join(tmpDir, "lib2", "corrupt.json"), "{nope");
    expect(library.list()).toHaveLength(1);
    library.delete(id);
    expect(library.list()).toHaveLength(0);
  });

  it("prunes beyond MAX_SESSIONS keeping the newest", () => {
    const library = new SessionLibrary(path.join(tmpDir, "lib3"));
    for (let i = 0; i < MAX_SESSIONS + 5; i++) {
      const id = library.newId();
      library.store(id).save("k", [{ role: "user", content: "hi" }], [{ kind: "user", text: `session ${i}` }]);
      // distinct savedAt per file
      const file = library.store(id).file;
      const payload = JSON.parse(fs.readFileSync(file, "utf-8"));
      payload.savedAt = i;
      fs.writeFileSync(file, JSON.stringify(payload));
    }
    const sessions = library.list();
    expect(sessions).toHaveLength(MAX_SESSIONS);
    expect(sessions[0]?.title).toBe(`session ${MAX_SESSIONS + 4}`);
    expect(fs.readdirSync(path.join(tmpDir, "lib3")).filter((f) => f.endsWith(".json"))).toHaveLength(MAX_SESSIONS);
  });

  it("returns [] for a directory that doesn't exist yet", () => {
    expect(new SessionLibrary(path.join(tmpDir, "missing")).list()).toEqual([]);
  });
});
