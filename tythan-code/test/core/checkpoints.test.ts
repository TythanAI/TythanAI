import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { CheckpointStore, MAX_CHECKPOINT_FILE_BYTES, MAX_CHECKPOINTS_PER_WORKSPACE } from "../../src/core/checkpoints";

let tmpDir: string;
let workspace: string;
let storageDir: string;
let store: CheckpointStore;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-cp-"));
  workspace = path.join(tmpDir, "workspace");
  fs.mkdirSync(workspace);
  storageDir = path.join(tmpDir, "checkpoint_storage");
  store = new CheckpointStore(workspace, storageDir);
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("CheckpointStore", () => {
  it("creates no directory until a change is committed", () => {
    expect(fs.existsSync(storageDir)).toBe(false);
    store.beginTurn("did nothing");
    expect(store.commitTurn()).toBeUndefined();
    expect(fs.existsSync(storageDir)).toBe(false);
  });

  it("records and commits a checkpoint", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");

    store.beginTurn("edit a.txt");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    const cp = store.commitTurn();

    expect(cp).toBeDefined();
    expect(cp?.label).toBe("edit a.txt");
    expect(cp?.changes).toHaveLength(1);
    expect(cp?.changes[0]?.path).toBe(target);
    expect(cp?.changes[0]?.existedBefore).toBe(true);
    expect(cp?.changes[0]?.beforeContent).toBe("v1");
    expect(fs.existsSync(storageDir)).toBe(true);
  });

  it("marks existedBefore false for a new file", () => {
    const target = path.join(workspace, "new.txt");
    store.beginTurn("create new.txt");
    store.recordBefore(target); // doesn't exist yet
    fs.writeFileSync(target, "content");
    const cp = store.commitTurn();
    expect(cp?.changes[0]?.existedBefore).toBe(false);
    expect(cp?.changes[0]?.beforeContent).toBeUndefined();
  });

  it("keeps the first pre-turn state when the same file is touched twice", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    store.beginTurn("double edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    store.recordBefore(target); // same path again — ignored
    fs.writeFileSync(target, "v3");
    const cp = store.commitTurn();
    expect(cp?.changes).toHaveLength(1);
    expect(cp?.changes[0]?.beforeContent).toBe("v1");
  });

  it("is a no-op when recordBefore is called without beginTurn", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    store.recordBefore(target); // no beginTurn() called
    expect(store.commitTurn()).toBeUndefined();
  });

  it("skips directories instead of recording a bogus change", () => {
    const target = path.join(workspace, "a_directory");
    fs.mkdirSync(target);
    store.beginTurn("oops, wrote to a directory");
    store.recordBefore(target);
    expect(store.commitTurn()).toBeUndefined();
    expect(fs.statSync(target).isDirectory()).toBe(true);
  });

  it("skips non-UTF-8 files instead of corrupting them", () => {
    const target = path.join(workspace, "legacy.txt");
    fs.writeFileSync(target, Buffer.from([0x63, 0x61, 0x66, 0xe9])); // "caf\xE9" — not valid UTF-8
    store.beginTurn("touch legacy file");
    store.recordBefore(target);
    const cp = store.commitTurn();
    expect(cp).toBeDefined();
    expect(cp?.changes).toEqual([]);
    expect(cp?.skippedBinary).toEqual([target]);
    expect(fs.readFileSync(target)).toEqual(Buffer.from([0x63, 0x61, 0x66, 0xe9]));
  });

  it("skips oversized files but still reports them alongside real changes", () => {
    const big = path.join(workspace, "big.txt");
    fs.writeFileSync(big, Buffer.alloc(MAX_CHECKPOINT_FILE_BYTES + 1, "x"));
    const small = path.join(workspace, "small.txt");
    fs.writeFileSync(small, "v1");

    store.beginTurn("touch both");
    store.recordBefore(big);
    store.recordBefore(small);
    const cp = store.commitTurn();
    expect(cp?.changes.map((c) => c.path)).toEqual([small]);
    expect(cp?.skippedLarge).toEqual([big]);
  });

  it("undoes a modified file back to its pre-turn content", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    store.beginTurn("edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    store.commitTurn();

    const restored = store.undoLast();
    expect(restored).toBeDefined();
    expect(fs.readFileSync(target, "utf-8")).toBe("v1");
  });

  it("undoes a newly created file by deleting it", () => {
    const target = path.join(workspace, "new.txt");
    store.beginTurn("create");
    store.recordBefore(target);
    fs.writeFileSync(target, "content");
    store.commitTurn();

    store.undoLast();
    expect(fs.existsSync(target)).toBe(false);
  });

  it("returns undefined when undoing an empty store", () => {
    expect(store.undoLast()).toBeUndefined();
  });

  it("pops one checkpoint at a time", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");

    store.beginTurn("first edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    store.commitTurn();

    store.beginTurn("second edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v3");
    store.commitTurn();

    expect(fs.readFileSync(target, "utf-8")).toBe("v3");
    store.undoLast();
    expect(fs.readFileSync(target, "utf-8")).toBe("v2");
    store.undoLast();
    expect(fs.readFileSync(target, "utf-8")).toBe("v1");
    expect(store.undoLast()).toBeUndefined();
  });

  it("refuses to touch paths outside its own workspace", () => {
    const outside = path.join(tmpDir, "outside.txt");
    fs.writeFileSync(outside, "safe");

    store.beginTurn("malicious");
    // @ts-expect-error reaching into private state to simulate a
    // corrupted/tampered checkpoint file that points outside the workspace.
    store["current"].changes.push({ path: outside, existedBefore: true, beforeContent: "HACKED" });
    store.commitTurn();

    store.undoLast();
    expect(fs.readFileSync(outside, "utf-8")).toBe("safe");
  });

  it("refuses a symlink pointing outside the workspace at undo time", () => {
    const outside = path.join(tmpDir, "outside.txt");
    fs.writeFileSync(outside, "safe");
    const linkPath = path.join(workspace, "link.txt");

    store.beginTurn("edit via what was a real path");
    // @ts-expect-error reaching into private state
    store["current"].changes.push({ path: linkPath, existedBefore: true, beforeContent: "HACKED" });
    store.commitTurn();

    // Simulate the path becoming a symlink to something outside the
    // workspace after the checkpoint was recorded.
    fs.symlinkSync(outside, linkPath);

    store.undoLast();
    expect(fs.readFileSync(outside, "utf-8")).toBe("safe");
  });

  it("lists checkpoints most-recent first", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    for (let i = 0; i < 3; i++) {
      store.beginTurn(`edit ${i}`);
      store.recordBefore(target);
      fs.writeFileSync(target, `v${i + 2}`);
      store.commitTurn();
    }
    const labels = store.list().map((cp) => cp.label);
    expect(labels).toEqual(["edit 2", "edit 1", "edit 0"]);
  });

  it("reports the true total via count() even when list() is limited", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v0");
    for (let i = 0; i < 5; i++) {
      store.beginTurn(`edit ${i}`);
      store.recordBefore(target);
      fs.writeFileSync(target, `v${i + 1}`);
      store.commitTurn();
    }
    expect(store.count()).toBe(5);
    expect(store.list(2)).toHaveLength(2);
  });

  it("returns nothing for list(0)", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    store.beginTurn("edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    store.commitTurn();

    expect(store.list(0)).toEqual([]);
    expect(store.list(10)).not.toEqual([]);
  });

  it("prunes the oldest checkpoints beyond the retention cap", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v0");
    const total = MAX_CHECKPOINTS_PER_WORKSPACE + 3;
    for (let i = 0; i < total; i++) {
      store.beginTurn(`edit ${i}`);
      store.recordBefore(target);
      fs.writeFileSync(target, `v${i + 1}`);
      store.commitTurn();
    }
    expect(store.count()).toBe(MAX_CHECKPOINTS_PER_WORKSPACE);
    const labels = store.list(MAX_CHECKPOINTS_PER_WORKSPACE).map((cp) => cp.label);
    // Most recent first; the oldest 3 ("edit 0", "edit 1", "edit 2") were pruned.
    expect(labels[0]).toBe(`edit ${total - 1}`);
    expect(labels).not.toContain("edit 0");
    expect(labels).not.toContain("edit 1");
    expect(labels).not.toContain("edit 2");
  }, 10_000);

  it("persists across store instances (survives a restart)", () => {
    const target = path.join(workspace, "a.txt");
    fs.writeFileSync(target, "v1");
    store.beginTurn("edit");
    store.recordBefore(target);
    fs.writeFileSync(target, "v2");
    store.commitTurn();

    const store2 = new CheckpointStore(workspace, storageDir);
    const restored = store2.undoLast();
    expect(restored).toBeDefined();
    expect(fs.readFileSync(target, "utf-8")).toBe("v1");
  });

  it("does not crash undoing a bogus directory entry left by an older version", () => {
    const aDirectory = path.join(workspace, "a_directory");
    fs.mkdirSync(aDirectory);
    store.beginTurn("bogus entry");
    // @ts-expect-error reaching into private state to simulate data written
    // by a hypothetical older/buggy version that didn't skip directories.
    store["current"].changes.push({ path: aDirectory, existedBefore: false, beforeContent: undefined });
    store.commitTurn();

    expect(() => store.undoLast()).not.toThrow();
    expect(fs.statSync(aDirectory).isDirectory()).toBe(true);
  });
});
