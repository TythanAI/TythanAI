import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { OverlayWorkspace } from "../../src/core/changeset";
import { ToolError } from "../../src/core/tools";

let tmpDir: string;
let ws: OverlayWorkspace;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-overlay-"));
  ws = new OverlayWorkspace(tmpDir);
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("OverlayWorkspace staging", () => {
  it("stages a write without touching disk", () => {
    const message = ws.writeFile("new.txt", "hello");
    expect(message).toContain("Staged");
    expect(fs.existsSync(path.join(tmpDir, "new.txt"))).toBe(false);
    expect(ws.changes()).toHaveLength(1);
    expect(ws.changes()[0]).toMatchObject({ relPath: "new.txt", before: undefined, after: "hello" });
  });

  it("records the on-disk content as `before` when overwriting an existing file", () => {
    fs.writeFileSync(path.join(tmpDir, "a.txt"), "original");
    ws.writeFile("a.txt", "changed");
    expect(ws.changes()[0]).toMatchObject({ before: "original", after: "changed" });
    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("original"); // disk untouched
  });

  it("keeps the original `before` across repeated writes to the same file", () => {
    fs.writeFileSync(path.join(tmpDir, "a.txt"), "v0");
    ws.writeFile("a.txt", "v1");
    ws.writeFile("a.txt", "v2");
    expect(ws.changes()).toHaveLength(1);
    expect(ws.changes()[0]).toMatchObject({ before: "v0", after: "v2" });
  });

  it("read_file sees staged content", () => {
    ws.writeFile("src/x.ts", "const a = 1;\nconst b = 2;");
    const text = ws.readFile("src/x.ts");
    expect(text).toContain("const a = 1;");
    expect(text).toContain("const b = 2;");
  });

  it("edit_file composes on top of a staged write", () => {
    fs.writeFileSync(path.join(tmpDir, "a.txt"), "alpha beta");
    ws.editFile("a.txt", "alpha", "ALPHA");
    ws.editFile("a.txt", "beta", "BETA");
    expect(ws.changes()).toHaveLength(1);
    expect(ws.changes()[0]?.after).toBe("ALPHA BETA");
    expect(fs.readFileSync(path.join(tmpDir, "a.txt"), "utf-8")).toBe("alpha beta");
  });

  it("edit_file on a staged new file works", () => {
    ws.writeFile("new.ts", "let x = 1;");
    ws.editFile("new.ts", "x = 1", "x = 2");
    expect(ws.changes()[0]?.after).toBe("let x = 2;");
  });

  it("list_files and search include staged new files", () => {
    ws.writeFile("staged/only.ts", "function findMeHere() {}");
    expect(ws.listFiles("**/*.ts")).toContain("staged/only.ts");
    expect(ws.search("findMeHere")).toContain("staged/only.ts:1");
  });

  it("search sees staged content of an existing file, not the disk content", () => {
    fs.writeFileSync(path.join(tmpDir, "a.txt"), "old needle");
    ws.writeFile("a.txt", "new needle");
    const hits = ws.search("new needle");
    expect(hits).toContain("a.txt:1");
    expect(ws.search("old needle")).toBe("(no matches)");
  });

  it("still confines staged paths to the workspace", () => {
    expect(() => ws.writeFile("../escape.txt", "nope")).toThrow(ToolError);
  });

  it("rejects staging over a directory", () => {
    fs.mkdirSync(path.join(tmpDir, "adir"));
    expect(() => ws.writeFile("adir", "nope")).toThrow(ToolError);
  });

  it("editFile with a bad old_string reports the usual ToolError", () => {
    ws.writeFile("a.txt", "content");
    expect(() => ws.editFile("a.txt", "missing", "x")).toThrow(/not found in file/);
  });
});
