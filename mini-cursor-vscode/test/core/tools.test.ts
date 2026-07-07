import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { describe, expect, it, beforeEach, afterEach } from "vitest";

import { ToolError, Workspace, expandMentions, globToRegExp, truncate } from "../../src/core/tools";

function makeTmpWorkspace(): { dir: string; ws: Workspace } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mini-cursor-test-"));
  return { dir, ws: new Workspace(dir) };
}

describe("truncate", () => {
  it("leaves short text unchanged", () => {
    expect(truncate("short", 100)).toBe("short");
  });

  it("truncates and appends a notice", () => {
    const text = "x".repeat(50);
    const out = truncate(text, 10);
    expect(out.startsWith("x".repeat(10))).toBe(true);
    expect(out).toContain("truncated, 40 more characters");
  });
});

describe("globToRegExp", () => {
  it("matches everything with the default pattern", () => {
    const rx = globToRegExp("**/*");
    expect(rx.test("a.py")).toBe(true);
    expect(rx.test("src/app.py")).toBe(true);
    expect(rx.test("src/nested/deep/file.txt")).toBe(true);
  });

  it("matches a specific extension anywhere", () => {
    const rx = globToRegExp("**/*.py");
    expect(rx.test("app.py")).toBe(true);
    expect(rx.test("src/app.py")).toBe(true);
    expect(rx.test("README.md")).toBe(false);
  });

  it("matches a specific directory prefix", () => {
    const rx = globToRegExp("src/*.ts");
    expect(rx.test("src/a.ts")).toBe(true);
    expect(rx.test("src/nested/a.ts")).toBe(false);
    expect(rx.test("a.ts")).toBe(false);
  });
});

describe("Workspace", () => {
  let dir: string;
  let ws: Workspace;

  beforeEach(() => {
    ({ dir, ws } = makeTmpWorkspace());
    fs.mkdirSync(path.join(dir, "src"));
    fs.writeFileSync(path.join(dir, "src", "app.py"), "def main():\n    print('hello')\n");
    fs.writeFileSync(path.join(dir, "README.md"), "# Demo\nhello world\n");
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("reads a file with line numbers", () => {
    const out = ws.readFile("src/app.py");
    expect(out).toContain("1\tdef main():");
    expect(out).toContain("print('hello')");
  });

  it("throws for a missing file", () => {
    expect(() => ws.readFile("nope.py")).toThrow(/not found/);
  });

  it("blocks path traversal", () => {
    expect(() => ws.readFile("../../etc/passwd")).toThrow(/escapes/);
    expect(() => ws.resolve("../outside.txt")).toThrow(/escapes/);
  });

  it("blocks absolute paths outside the workspace", () => {
    expect(() => ws.resolve("/etc/passwd")).toThrow(/escapes/);
  });

  it("writes and overwrites files, creating parent dirs", () => {
    const msg = ws.writeFile("new/dir/file.txt", "content");
    expect(msg).toContain("file.txt");
    expect(fs.readFileSync(path.join(dir, "new", "dir", "file.txt"), "utf-8")).toBe("content");
    ws.writeFile("new/dir/file.txt", "changed");
    expect(fs.readFileSync(path.join(dir, "new", "dir", "file.txt"), "utf-8")).toBe("changed");
  });

  it("edits a file by exact string replace", () => {
    ws.editFile("src/app.py", "print('hello')", "print('bye')");
    expect(fs.readFileSync(path.join(dir, "src", "app.py"), "utf-8")).toContain("print('bye')");
  });

  it("requires the old_string to be unique unless replace_all is set", () => {
    fs.writeFileSync(path.join(dir, "dup.txt"), "aaa\naaa\n");
    expect(() => ws.editFile("dup.txt", "aaa", "bbb")).toThrow(/2 times/);
    ws.editFile("dup.txt", "aaa", "bbb", true);
    expect(fs.readFileSync(path.join(dir, "dup.txt"), "utf-8")).toBe("bbb\nbbb\n");
  });

  it("rejects an edit whose old_string isn't found", () => {
    expect(() => ws.editFile("src/app.py", "no such text", "x")).toThrow(/not found/);
  });

  it("rejects writing to a path that is a directory", () => {
    expect(() => ws.writeFile("src", "oops")).toThrow(/[Nn]ot a regular file/);
  });

  it("lists files matching a glob", () => {
    const out = ws.listFiles("**/*.py");
    expect(out).toContain("src/app.py");
    expect(out).not.toContain("README.md");
  });

  it("skips junk directories when listing", () => {
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "config"), "x");
    expect(ws.listFiles("**/*")).not.toContain(".git");
  });

  it("searches file contents with a regex", () => {
    const out = ws.search("hello", "**/*.py");
    expect(out).toContain("src/app.py:2");
    expect(out).not.toContain("README.md");
  });

  it("rejects an invalid regex", () => {
    expect(() => ws.search("(unclosed")).toThrow(/Invalid regex/);
  });

  it("runs a command and reports exit code", async () => {
    const out = await ws.runCommand("echo hi");
    expect(out).toContain("hi");
    expect(out).toContain("[exit code: 0]");
  });

  it("reports a non-zero exit code without throwing", async () => {
    const out = await ws.runCommand("exit 1");
    expect(out).toContain("[exit code: 1]");
  });

  it("times out a long-running command", async () => {
    // A real (short) timeout, not a mocked one — runCommand's timeout kills a
    // real child process, and that's exactly the behavior under test.
    const start = Date.now();
    const out = await ws.runCommand("sleep 5", 200);
    const elapsed = Date.now() - start;
    expect(out).toContain("timed out after 0.2s");
    expect(elapsed).toBeLessThan(4000);
  }, 10_000);
});

describe("expandMentions", () => {
  let dir: string;
  let ws: Workspace;

  beforeEach(() => {
    ({ dir, ws } = makeTmpWorkspace());
    fs.writeFileSync(path.join(dir, "notes.md"), "secret plans\n");
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("expands an @file mention with the file's contents", () => {
    const out = expandMentions("summarize @notes.md please", ws);
    expect(out).toContain('file path="notes.md"');
    expect(out).toContain("secret plans");
  });

  it("leaves non-file mentions untouched", () => {
    expect(expandMentions("email me @user.name", ws)).toBe("email me @user.name");
  });

  it("ignores mentions that try to escape the workspace", () => {
    expect(expandMentions("look at @../../etc/passwd", ws)).toBe("look at @../../etc/passwd");
  });
});

describe("ToolError", () => {
  it("is a real Error subclass", () => {
    const err = new ToolError("boom");
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("boom");
  });
});
