/**
 * Project rules files — the .cursorrules idea: a plain-text file at the
 * workspace root whose contents are appended to the system prompt, so a
 * project can pin its conventions ("always use pnpm", "tests live in
 * tests/", ...) without the user repeating them every session.
 *
 * Read fresh on every turn (it's one tiny file read), so edits take effect
 * immediately with no watcher wiring.
 */

import * as fs from "node:fs";
import * as path from "node:path";

// First match wins. `.cursorrules` is supported so an existing Cursor
// project's rules keep working unchanged.
export const RULES_FILENAMES = [".tythanrules", ".cursorrules", "AGENTS.md"];

export const MAX_RULES_CHARS = 8_000;

export interface RulesText {
  source: string;
  text: string;
}

export function loadRulesText(workspaceRoot: string): RulesText | undefined {
  for (const name of RULES_FILENAMES) {
    const file = path.join(workspaceRoot, name);
    let text: string;
    try {
      if (!fs.statSync(file).isFile()) {
        continue;
      }
      text = fs.readFileSync(file, "utf-8");
    } catch {
      continue;
    }
    const trimmed = text.trim();
    if (!trimmed) {
      continue;
    }
    return {
      source: name,
      text: trimmed.length > MAX_RULES_CHARS ? trimmed.slice(0, MAX_RULES_CHARS) + "\n... [rules truncated]" : trimmed,
    };
  }
  return undefined;
}
