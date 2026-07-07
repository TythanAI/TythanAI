import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MAX_RULES_CHARS, loadRulesText } from "../../src/core/rules";

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-rules-"));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("loadRulesText", () => {
  it("returns undefined when no rules file exists", () => {
    expect(loadRulesText(tmpDir)).toBeUndefined();
  });

  it("loads .tythanrules", () => {
    fs.writeFileSync(path.join(tmpDir, ".tythanrules"), "Always use pnpm.\n");
    expect(loadRulesText(tmpDir)).toEqual({ source: ".tythanrules", text: "Always use pnpm." });
  });

  it("falls back to .cursorrules so Cursor projects keep working", () => {
    fs.writeFileSync(path.join(tmpDir, ".cursorrules"), "Prefer composition over inheritance.");
    expect(loadRulesText(tmpDir)?.source).toBe(".cursorrules");
  });

  it("prefers .tythanrules over .cursorrules when both exist", () => {
    fs.writeFileSync(path.join(tmpDir, ".tythanrules"), "tythan rules");
    fs.writeFileSync(path.join(tmpDir, ".cursorrules"), "cursor rules");
    expect(loadRulesText(tmpDir)).toEqual({ source: ".tythanrules", text: "tythan rules" });
  });

  it("skips empty/whitespace-only files and keeps looking", () => {
    fs.writeFileSync(path.join(tmpDir, ".tythanrules"), "   \n  ");
    fs.writeFileSync(path.join(tmpDir, ".cursorrules"), "real rules");
    expect(loadRulesText(tmpDir)?.text).toBe("real rules");
  });

  it("truncates oversized rules files", () => {
    fs.writeFileSync(path.join(tmpDir, ".tythanrules"), "x".repeat(MAX_RULES_CHARS + 500));
    const rules = loadRulesText(tmpDir);
    expect(rules?.text.length).toBeLessThan(MAX_RULES_CHARS + 100);
    expect(rules?.text).toContain("[rules truncated]");
  });

  it("ignores a directory with a rules filename", () => {
    fs.mkdirSync(path.join(tmpDir, ".tythanrules"));
    expect(loadRulesText(tmpDir)).toBeUndefined();
  });
});
