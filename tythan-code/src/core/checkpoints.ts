/**
 * File-level checkpoints for undo.
 *
 * Before write_file/edit_file mutate a path, the agent records that path's
 * pre-turn content here. When the turn ends, everything recorded during it
 * is persisted as one checkpoint (a JSON file under a caller-supplied
 * storage directory). Undo pops the most recent checkpoint and restores
 * every file it touched to its pre-turn state (or deletes it, if the file
 * didn't exist before the turn).
 *
 * Scope, on purpose: this only covers write_file/edit_file, the two tools
 * Tythan Code fully controls and already diffs before applying. run_command
 * can do anything — there is no honest way to snapshot and revert that
 * generically, so it isn't covered. This is a safety net for agent-authored
 * file edits, not a full VM undo.
 *
 * This module intentionally carries forward every fix found reviewing the
 * original Python port: never checkpoint a non-regular-file target (avoids
 * an EISDIR crash on undo), skip (and honestly report) files that aren't
 * valid UTF-8 instead of silently corrupting them, use a monotonic sequence
 * number rather than a wall-clock timestamp for ordering, and re-resolve
 * paths against the live filesystem at undo time so a symlink introduced
 * after the checkpoint can't smuggle a write outside the workspace.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";

import { realpathAsFarAsPossible } from "./tools";

// Skip checkpointing files above this size (still allowed to be written,
// just not covered by undo) so a single huge file can't blow up disk usage.
export const MAX_CHECKPOINT_FILE_BYTES = 5_000_000;

// Retention cap per workspace so checkpoints don't accumulate forever.
export const MAX_CHECKPOINTS_PER_WORKSPACE = 50;

export interface FileChange {
  /** absolute path, resolved inside the workspace it was recorded for */
  path: string;
  existedBefore: boolean;
  /** undefined means the file did not exist before this turn */
  beforeContent: string | undefined;
}

export interface Checkpoint {
  id: string;
  createdAt: number;
  label: string;
  changes: FileChange[];
  skippedLarge: string[];
  skippedBinary: string[];
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function fileChangeFromJson(raw: unknown): FileChange | null {
  if (!isPlainObject(raw) || typeof raw.path !== "string") {
    return null;
  }
  return {
    path: raw.path,
    existedBefore: Boolean(raw.existedBefore),
    beforeContent: typeof raw.beforeContent === "string" ? raw.beforeContent : undefined,
  };
}

function checkpointFromJson(raw: unknown): Checkpoint | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  const r = raw;
  if (typeof r.id !== "string" && typeof r.id !== "number") {
    return null;
  }
  const createdAt = typeof r.createdAt === "number" ? r.createdAt : Number(r.createdAt);
  if (!Number.isFinite(createdAt)) {
    return null;
  }
  const changes = Array.isArray(r.changes)
    ? (r.changes.map(fileChangeFromJson).filter((c): c is FileChange => c !== null))
    : [];
  return {
    id: String(r.id),
    createdAt,
    label: typeof r.label === "string" ? r.label : "",
    changes,
    skippedLarge: Array.isArray(r.skippedLarge) ? r.skippedLarge.filter((x): x is string => typeof x === "string") : [],
    skippedBinary: Array.isArray(r.skippedBinary)
      ? r.skippedBinary.filter((x): x is string => typeof x === "string")
      : [],
  };
}

function toJson(cp: Checkpoint): object {
  return {
    id: cp.id,
    createdAt: cp.createdAt,
    label: cp.label,
    changes: cp.changes.map((c) => ({
      path: c.path,
      existedBefore: c.existedBefore,
      beforeContent: c.beforeContent ?? null,
    })),
    skippedLarge: cp.skippedLarge,
    skippedBinary: cp.skippedBinary,
  };
}

/** Stable per-workspace storage key, so unrelated projects don't collide
 * when the caller derives a directory from `CHECKPOINTS_ROOT/<key>`. */
export function workspaceStorageKey(workspaceRoot: string): string {
  return crypto.createHash("sha256").update(path.resolve(workspaceRoot)).digest("hex").slice(0, 16);
}

function isValidUtf8(buf: Buffer): string | null {
  try {
    // { fatal: true } makes TextDecoder throw on invalid byte sequences,
    // unlike Buffer#toString("utf-8") which silently replaces them — exactly
    // the strict check needed to detect a non-UTF-8 file before ever storing
    // a lossy copy of it.
    return new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch {
    return null;
  }
}

export class CheckpointStore {
  readonly root: string;
  readonly dir: string;
  private current: Checkpoint | null = null;

  constructor(workspaceRoot: string, storageDir: string) {
    this.root = realpathAsFarAsPossible(path.resolve(workspaceRoot));
    this.dir = storageDir;
  }

  /** Start collecting changes for a new turn. Call once per user turn. */
  beginTurn(label: string): void {
    this.current = {
      id: crypto.randomUUID().replace(/-/g, "").slice(0, 12),
      createdAt: Date.now() / 1000,
      label: label.split(/\s+/).filter(Boolean).join(" ").slice(0, 120),
      changes: [],
      skippedLarge: [],
      skippedBinary: [],
    };
  }

  /** Capture `target`'s current (pre-mutation) content, once per turn per path.
   *
   * Only ever called for paths write_file/edit_file are *about* to touch —
   * the actual write/edit may still go on to fail its own validation (e.g.
   * `target` turns out to be a directory, or an edit's oldString doesn't
   * match). This deliberately records nothing in that case rather than a
   * checkpoint entry for a change that never happened.
   */
  recordBefore(target: string): void {
    if (this.current === null) {
      return;
    }
    const key = target;
    if (this.current.changes.some((c) => c.path === key)) {
      return; // keep the *first* pre-turn state if the same file is touched twice
    }
    let stat: fs.Stats | undefined;
    try {
      stat = fs.statSync(target);
    } catch {
      stat = undefined;
    }
    if (stat && !stat.isFile()) {
      return; // not a regular file (e.g. a directory) — nothing meaningful to checkpoint
    }
    let beforeContent: string | undefined;
    if (stat) {
      if (stat.size > MAX_CHECKPOINT_FILE_BYTES) {
        if (!this.current.skippedLarge.includes(key)) {
          this.current.skippedLarge.push(key);
        }
        return;
      }
      let raw: Buffer;
      try {
        raw = fs.readFileSync(target);
      } catch {
        return;
      }
      const decoded = isValidUtf8(raw);
      if (decoded === null) {
        // Not valid UTF-8: a lossy decode would silently corrupt the byte
        // content before it's even stored, making undo "restore" an
        // already-mangled version. Refuse to checkpoint it instead — same
        // honest-skip treatment as an oversized file.
        if (!this.current.skippedBinary.includes(key)) {
          this.current.skippedBinary.push(key);
        }
        return;
      }
      beforeContent = decoded;
    } else {
      beforeContent = undefined;
    }
    this.current.changes.push({ path: key, existedBefore: stat !== undefined, beforeContent });
  }

  /** Persist the turn's recorded changes as one checkpoint. Returns it, or
   * undefined if the turn recorded nothing at all (no file was touched).
   *
   * A turn that touched only skipped (oversized/binary) files still comes
   * back defined, so the caller can tell the user those files aren't
   * covered by undo — but nothing is written to disk for it, since there is
   * no actual undo-able state to persist or list.
   */
  commitTurn(): Checkpoint | undefined {
    const cp = this.current;
    this.current = null;
    if (cp === null) {
      return undefined;
    }
    if (cp.changes.length === 0 && cp.skippedLarge.length === 0 && cp.skippedBinary.length === 0) {
      return undefined;
    }
    if (cp.changes.length === 0) {
      return cp; // nothing to persist — just skipped-file bookkeeping to report
    }
    fs.mkdirSync(this.dir, { recursive: true });
    // A monotonic sequence number (not just the wall-clock timestamp) so
    // ordering stays correct even when two turns commit within the same
    // clock tick — filename sort must match commit order for undo to ever
    // pop the right one.
    const seq = this.nextSequence();
    const filePath = path.join(this.dir, `${String(seq).padStart(10, "0")}_${cp.id}.json`);
    fs.writeFileSync(filePath, JSON.stringify(toJson(cp), null, 2), "utf-8");
    this.prune();
    return cp;
  }

  private nextSequence(): number {
    let maxSeq = -1;
    for (const f of this.files()) {
      const parsed = parseInt(path.basename(f).split("_", 1)[0] ?? "", 10);
      if (Number.isFinite(parsed)) {
        maxSeq = Math.max(maxSeq, parsed);
      }
    }
    return maxSeq + 1;
  }

  private files(): string[] {
    if (!fs.existsSync(this.dir) || !fs.statSync(this.dir).isDirectory()) {
      return [];
    }
    return fs
      .readdirSync(this.dir)
      .filter((f) => f.endsWith(".json"))
      .sort()
      .map((f) => path.join(this.dir, f));
  }

  private prune(): void {
    const files = this.files();
    const excess = files.length - MAX_CHECKPOINTS_PER_WORKSPACE;
    for (let i = 0; i < Math.max(excess, 0); i++) {
      const f = files[i];
      if (f) {
        try {
          fs.unlinkSync(f);
        } catch {
          // best-effort
        }
      }
    }
  }

  /** Total number of checkpoints retained on disk (may exceed what list() returns). */
  count(): number {
    return this.files().length;
  }

  /** Most recent first. */
  list(limit = 10): Checkpoint[] {
    if (limit <= 0) {
      return [];
    }
    const files = this.files();
    const tail = files.slice(-limit).reverse();
    const out: Checkpoint[] = [];
    for (const f of tail) {
      try {
        const parsed = checkpointFromJson(JSON.parse(fs.readFileSync(f, "utf-8")));
        if (parsed) {
          out.push(parsed);
        }
      } catch {
        continue;
      }
    }
    return out;
  }

  /** Pop and apply the most recent checkpoint. Returns it, or undefined if empty.
   *
   * Best-effort per file: a problem restoring one change (permission error,
   * a path that no longer makes sense, a symlink now pointing somewhere
   * unexpected) doesn't abort the rest of the checkpoint or throw — every
   * apply below and the checkpoint file itself are always cleaned up.
   */
  undoLast(): Checkpoint | undefined {
    const files = this.files();
    const last = files[files.length - 1];
    if (last === undefined) {
      return undefined;
    }
    let cp: Checkpoint | null;
    try {
      cp = checkpointFromJson(JSON.parse(fs.readFileSync(last, "utf-8")));
    } catch {
      cp = null;
    }
    if (cp === null) {
      this.safeUnlink(last);
      return undefined;
    }
    for (const change of cp.changes) {
      try {
        // Re-resolve at undo time (not just the raw stored path) so a
        // symlink introduced after the checkpoint was recorded can't
        // smuggle the write outside the workspace.
        const target = realpathAsFarAsPossible(change.path);
        const rel = path.relative(this.root, target);
        if (rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
          continue; // refuse to touch anything outside this checkpoint's workspace
        }
        if (change.existedBefore) {
          fs.mkdirSync(path.dirname(target), { recursive: true });
          fs.writeFileSync(target, change.beforeContent ?? "", "utf-8");
        } else if (fs.existsSync(target) && fs.statSync(target).isFile()) {
          fs.unlinkSync(target);
        }
      } catch {
        continue; // best-effort: skip this file, still process the rest
      }
    }
    this.safeUnlink(last);
    return cp;
  }

  private safeUnlink(file: string): void {
    try {
      fs.unlinkSync(file);
    } catch {
      // best-effort
    }
  }
}
