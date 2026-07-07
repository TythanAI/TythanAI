/**
 * Tool definitions and executors — vscode-independent so this can be unit
 * tested without a running editor.
 *
 * Every file operation is confined to the workspace root: model-supplied
 * paths are resolved and rejected if they escape it. Deliberately does NOT
 * use `fs.globSync` (added in recent Node releases) since a VS Code
 * extension host runs whatever Node/Electron version that particular VS
 * Code build ships with, not the system Node — relying on a brand-new fs
 * API would silently break on older (but still supported) VS Code versions.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { spawn } from "node:child_process";

export const MAX_TOOL_OUTPUT_CHARS = 30_000;
export const MAX_READ_LINES = 2_000;
export const COMMAND_TIMEOUT_MS = 120_000;
export const MAX_LIST_RESULTS = 500;
export const MAX_SEARCH_RESULTS = 200;

// Directories we never descend into when listing/searching.
export const SKIP_DIRS = new Set([
  ".git",
  "node_modules",
  "__pycache__",
  ".venv",
  "venv",
  ".mypy_cache",
  ".ruff_cache",
  "dist",
  "out",
  "build",
  ".pytest_cache",
  ".vscode-test",
]);

export class ToolError extends Error {}

export function truncate(text: string, limit: number = MAX_TOOL_OUTPUT_CHARS): string {
  if (text.length <= limit) {
    return text;
  }
  return text.slice(0, limit) + `\n... [truncated, ${text.length - limit} more characters]`;
}

/** Mirrors Python's `Path.resolve(strict=False)`: resolves symlinks for the
 * longest existing prefix, then rejoins whatever suffix doesn't exist yet
 * (so a path a tool is about to *create* can still be resolved safely). */
export function realpathAsFarAsPossible(target: string): string {
  let current = target;
  const suffix: string[] = [];
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      const real = fs.realpathSync.native(current);
      return suffix.length > 0 ? path.join(real, ...suffix.slice().reverse()) : real;
    } catch {
      const parent = path.dirname(current);
      if (parent === current) {
        // Hit the filesystem root without finding an existing ancestor.
        return path.join(target, ...suffix.slice().reverse());
      }
      suffix.push(path.basename(current));
      current = parent;
    }
  }
}

/** Converts a simple glob pattern (`**`, `*`, literal segments — the subset
 * Tythan Code's tools ever pass) into a RegExp matched against a
 * forward-slash-joined relative path. */
export function globToRegExp(pattern: string): RegExp {
  const normalized = pattern.split(path.sep).join("/");
  let out = "";
  let i = 0;
  while (i < normalized.length) {
    const c = normalized[i];
    if (c === "*" && normalized[i + 1] === "*" && normalized[i + 2] === "/") {
      out += "(?:.*/)?";
      i += 3;
      continue;
    }
    if (c === "*" && normalized[i + 1] === "*") {
      out += ".*";
      i += 2;
      continue;
    }
    if (c === "*") {
      out += "[^/]*";
      i += 1;
      continue;
    }
    if (c === "?") {
      out += "[^/]";
      i += 1;
      continue;
    }
    if (c !== undefined && "\\^$.+|()[]{}".includes(c)) {
      out += "\\" + c;
      i += 1;
      continue;
    }
    out += c;
    i += 1;
  }
  return new RegExp(`^${out}$`);
}

export function walkFiles(root: string, cap: number): string[] {
  const results: string[] = [];
  const queue: string[] = [root];
  while (queue.length > 0 && results.length < cap) {
    const dir = queue.shift() as string;
    let names: string[];
    try {
      names = fs.readdirSync(dir);
    } catch {
      continue;
    }
    for (const name of names) {
      if (SKIP_DIRS.has(name)) {
        continue;
      }
      const abs = path.join(dir, name);
      let stat: fs.Stats;
      try {
        stat = fs.statSync(abs);
      } catch {
        continue; // broken symlink or a race with something deleting it
      }
      if (stat.isDirectory()) {
        queue.push(abs);
      } else if (stat.isFile()) {
        results.push(abs);
        if (results.length >= cap) {
          break;
        }
      }
    }
  }
  return results;
}

function isLikelyBinary(text: string): boolean {
  return text.slice(0, 1024).includes("\0");
}

export class Workspace {
  readonly root: string;

  constructor(root: string) {
    this.root = realpathAsFarAsPossible(path.resolve(root));
  }

  /** Resolve a model-supplied relative path, rejecting anything that escapes the workspace. */
  resolve(relPath: string): string {
    const raw = path.resolve(this.root, relPath);
    const resolved = realpathAsFarAsPossible(raw);
    const rel = path.relative(this.root, resolved);
    if (rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
      throw new ToolError(`Path escapes the workspace: ${relPath}`);
    }
    return resolved;
  }

  private relativeDisplay(absPath: string): string {
    return path.relative(this.root, absPath).split(path.sep).join("/");
  }

  // -- overridable file access --------------------------------------------
  // OverlayWorkspace (composer mode) reroutes these three so staged-but-not-
  // yet-applied changes are visible to every read-side tool.

  protected fileExists(target: string): boolean {
    return fs.existsSync(target) && fs.statSync(target).isFile();
  }

  protected readTextFile(target: string): string {
    return fs.readFileSync(target, "utf-8");
  }

  protected candidateFiles(cap: number): string[] {
    return walkFiles(this.root, cap);
  }

  // -- read-only tools ----------------------------------------------------

  /** Raw file content (no line numbers, no truncation) — for internal
   * consumers like the codebase index. Overlay-aware like readFile. */
  readRaw(relPath: string): string {
    const target = this.resolve(relPath);
    if (!this.fileExists(target)) {
      throw new ToolError(`File not found: ${relPath}`);
    }
    return this.readTextFile(target);
  }

  readFile(relPath: string, offset = 1, limit: number = MAX_READ_LINES): string {
    const target = this.resolve(relPath);
    if (!this.fileExists(target)) {
      throw new ToolError(`File not found: ${relPath}`);
    }
    let text: string;
    try {
      text = this.readTextFile(target);
    } catch (err) {
      throw new ToolError(`Cannot read ${relPath}: ${(err as Error).message}`);
    }
    const lines = text.split(/\r\n|\r|\n/);
    const start = Math.max(offset, 1);
    const window = lines.slice(start - 1, start - 1 + limit);
    if (window.length === 0 && lines.length > 0) {
      throw new ToolError(`offset ${start} is beyond end of file (${lines.length} lines)`);
    }
    const numbered = window.map((line, idx) => `${start + idx}\t${line}`).join("\n");
    const remaining = lines.length - (start - 1 + window.length);
    const suffix = remaining > 0 ? `\n... [${remaining} more lines — use offset=${start + window.length} to continue]` : "";
    return numbered ? truncate(numbered + suffix) : "(empty file)";
  }

  listFiles(pattern = "**/*"): string {
    const rx = globToRegExp(pattern);
    const files = this.candidateFiles(20_000)
      .map((abs) => this.relativeDisplay(abs))
      .filter((rel) => rx.test(rel))
      .sort();
    if (files.length === 0) {
      return "(no files match)";
    }
    if (files.length > MAX_LIST_RESULTS) {
      return files.slice(0, MAX_LIST_RESULTS).join("\n") + "\n... [more files omitted, narrow the pattern]";
    }
    return files.join("\n");
  }

  search(pattern: string, glob = "**/*"): string {
    let rx: RegExp;
    try {
      rx = new RegExp(pattern);
    } catch (err) {
      throw new ToolError(`Invalid regex: ${(err as Error).message}`);
    }
    const globRx = globToRegExp(glob);
    const hits: string[] = [];
    const files = this.candidateFiles(20_000)
      .map((abs) => ({ abs, rel: this.relativeDisplay(abs) }))
      .filter(({ rel }) => globRx.test(rel))
      .sort((a, b) => a.rel.localeCompare(b.rel));

    outer: for (const { abs, rel } of files) {
      let text: string;
      try {
        text = this.readTextFile(abs);
      } catch {
        continue;
      }
      if (isLikelyBinary(text)) {
        continue;
      }
      const lines = text.split(/\r\n|\r|\n/);
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i] ?? "";
        if (rx.test(line)) {
          hits.push(`${rel}:${i + 1}:${line.trim().slice(0, 300)}`);
          if (hits.length >= MAX_SEARCH_RESULTS) {
            hits.push("... [more matches omitted, narrow the search]");
            break outer;
          }
        }
      }
    }
    return hits.length > 0 ? hits.join("\n") : "(no matches)";
  }

  // -- mutating tools -------------------------------------------------------

  /** Validate a write and return {target, old} for diffing, without writing anything. */
  prepareWrite(relPath: string): { target: string; old: string } {
    const target = this.resolve(relPath);
    let old = "";
    if (this.fileExists(target)) {
      old = this.readTextFile(target);
    } else if (fs.existsSync(target)) {
      throw new ToolError(`Not a regular file: ${relPath}`);
    }
    return { target, old };
  }

  writeFile(relPath: string, content: string): string {
    const { target } = this.prepareWrite(relPath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content, "utf-8");
    return `Wrote ${content.length} characters to ${relPath}`;
  }

  /** Validate an edit and return {target, old, updated}, without writing anything. */
  prepareEdit(
    relPath: string,
    oldString: string,
    newString: string,
    replaceAll = false,
  ): { target: string; old: string; updated: string } {
    const target = this.resolve(relPath);
    if (!this.fileExists(target)) {
      throw new ToolError(`File not found: ${relPath}`);
    }
    const text = this.readTextFile(target);
    const count = countOccurrences(text, oldString);
    if (count === 0) {
      throw new ToolError("old_string not found in file — read the file and match it exactly");
    }
    if (count > 1 && !replaceAll) {
      throw new ToolError(`old_string appears ${count} times — make it unique or set replace_all=true`);
    }
    if (oldString === newString) {
      throw new ToolError("old_string and new_string are identical");
    }
    const updated = replaceAll
      ? text.split(oldString).join(newString)
      : replaceFirst(text, oldString, newString);
    return { target, old: text, updated };
  }

  editFile(relPath: string, oldString: string, newString: string, replaceAll = false): string {
    const { target, updated } = this.prepareEdit(relPath, oldString, newString, replaceAll);
    fs.writeFileSync(target, updated, "utf-8");
    return `Edited ${relPath}`;
  }

  /** Runs asynchronously (via `spawn`, not `spawnSync`) on purpose: a VS
   * Code extension host is typically shared by every installed extension,
   * so a long-running command executed synchronously would freeze the
   * editor UI and every other extension along with it, not just this one. */
  runCommand(command: string, timeoutMs: number = COMMAND_TIMEOUT_MS): Promise<string> {
    return new Promise((resolve, reject) => {
      let settled = false;
      let child: ReturnType<typeof spawn>;
      // `detached: true` on POSIX makes the child the leader of its own
      // process group instead of joining ours. That's required for the
      // timeout kill below: with `shell: true`, child.pid is the *shell's*
      // pid (e.g. `/bin/sh -c "sleep 5"`) — killing just that process often
      // leaves the actual command (sleep) running, since the shell doesn't
      // reliably forward signals to it. Signaling the whole process group
      // (kill(-pid)) reaches both.
      const usesProcessGroup = process.platform !== "win32";
      try {
        child = spawn(command, { cwd: this.root, shell: true, detached: usesProcessGroup });
      } catch (err) {
        reject(new ToolError(`Failed to run command: ${(err as Error).message}`));
        return;
      }

      let stdout = "";
      let stderr = "";
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        if (usesProcessGroup && child.pid) {
          try {
            process.kill(-child.pid, "SIGTERM");
            return;
          } catch {
            // Fall through to killing just the child if the group signal failed
            // (e.g. it already exited, or the group is otherwise gone).
          }
        }
        child.kill("SIGTERM");
      }, timeoutMs);

      child.stdout?.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf-8");
      });
      child.stderr?.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf-8");
      });

      child.on("error", (err) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        reject(new ToolError(`Failed to run command: ${err.message}`));
      });

      child.on("close", (code, signal) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        const parts: string[] = [];
        if (stdout) {
          parts.push(stdout);
        }
        if (stderr) {
          parts.push(`[stderr]\n${stderr}`);
        }
        if (timedOut) {
          parts.push(`[terminated: timed out after ${(timeoutMs / 1000).toFixed(1)}s]`);
        } else if (code !== null) {
          parts.push(`[exit code: ${code}]`);
        } else {
          parts.push(`[terminated by signal: ${signal ?? "unknown"}]`);
        }
        resolve(truncate(parts.join("\n")));
      });
    });
  }
}

function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) {
    return 0;
  }
  let count = 0;
  let idx = haystack.indexOf(needle);
  while (idx !== -1) {
    count++;
    idx = haystack.indexOf(needle, idx + needle.length);
  }
  return count;
}

function replaceFirst(haystack: string, needle: string, replacement: string): string {
  const idx = haystack.indexOf(needle);
  if (idx === -1) {
    return haystack;
  }
  return haystack.slice(0, idx) + replacement + haystack.slice(idx + needle.length);
}

// -- @file mentions ---------------------------------------------------------

const MENTION_RX = /@([A-Za-z0-9_\-./]+)/g;

/** Expand @path mentions: append the referenced files' contents to the message.
 * Unresolvable mentions (emails, handles, missing files) are left untouched. */
export function expandMentions(text: string, ws: Workspace): string {
  const seen = new Set<string>();
  let result = text;
  for (const match of text.matchAll(MENTION_RX)) {
    const name = match[1];
    if (!name || seen.has(name)) {
      continue;
    }
    seen.add(name);
    let target: string;
    try {
      target = ws.resolve(name);
    } catch {
      continue;
    }
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
      continue;
    }
    const content = truncate(fs.readFileSync(target, "utf-8"));
    result += `\n\n<file path="${name}">\n${content}\n</file>`;
  }
  return result;
}

// -- tool schemas -------------------------------------------------------------

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export const TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    name: "read_file",
    description:
      "Read a text file from the workspace. Returns the content with line numbers. " +
      "Call this before editing a file. Use offset/limit for large files.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path relative to the workspace root" },
        offset: { type: "integer", description: "1-based line to start reading from" },
        limit: { type: "integer", description: "Maximum number of lines to read" },
      },
      required: ["path"],
    },
  },
  {
    name: "write_file",
    description:
      "Create or overwrite a file in the workspace with the given content. " +
      "The user sees a diff and confirms before the write happens. " +
      "Always output the complete file content.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path relative to the workspace root" },
        content: { type: "string", description: "Full new file content" },
      },
      required: ["path", "content"],
    },
  },
  {
    name: "edit_file",
    description:
      "Replace an exact string in a file. old_string must appear exactly once " +
      "(or set replace_all to true). Read the file first so old_string matches exactly, " +
      "including whitespace. The user sees a diff and confirms before the edit happens.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path relative to the workspace root" },
        old_string: { type: "string", description: "Exact text to replace" },
        new_string: { type: "string", description: "Replacement text" },
        replace_all: { type: "boolean", description: "Replace every occurrence (default false)" },
      },
      required: ["path", "old_string", "new_string"],
    },
  },
  {
    name: "list_files",
    description:
      "List files in the workspace matching a glob pattern (e.g. '**/*.py', 'src/*.ts'). " +
      "Defaults to listing everything. Common junk directories (.git, node_modules, ...) are skipped.",
    inputSchema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: "Glob pattern, default '**/*'" },
      },
    },
  },
  {
    name: "search",
    description:
      "Search file contents in the workspace with a JavaScript-flavored regular expression. " +
      "Returns matching lines as path:line:text. Use glob to narrow which files are searched.",
    inputSchema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: "JavaScript regular expression" },
        glob: { type: "string", description: "Only search files matching this glob, e.g. '**/*.ts'" },
      },
      required: ["pattern"],
    },
  },
  {
    name: "security_scan",
    description:
      "Scan the workspace (or a subdirectory/file) for security issues: leaked " +
      "secrets and API keys, dangerous code patterns (eval, pickle, SQL built from " +
      "f-strings, shell=True, disabled TLS verification, ...) and insecure config " +
      "(wildcard CORS, JWT 'none', debug mode). Run this after writing or changing " +
      "code, and when the user asks for a security review. Returns findings with " +
      "severity, file and line.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Subdirectory or file to scan (default: whole workspace)" },
      },
    },
  },
  {
    name: "run_command",
    description:
      "Run a shell command in the workspace root and return its output " +
      "(stdout + stderr + exit code). The user confirms before the command runs. " +
      "Use for tests, builds, git, installs, etc. Not covered by /undo.",
    inputSchema: {
      type: "object",
      properties: {
        command: { type: "string", description: "The shell command to execute" },
      },
      required: ["command"],
    },
  },
];

export const MUTATING_TOOLS = new Set(["write_file", "edit_file", "run_command"]);
