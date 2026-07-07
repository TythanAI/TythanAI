/**
 * Composer support: an OverlayWorkspace stages every write_file/edit_file
 * into an in-memory changeset instead of touching disk, while read-side
 * tools (read_file, search, list_files) see the staged state — so the model
 * can build multi-file changes incrementally and read back its own edits.
 * Nothing lands on disk until the user reviews the changeset and the caller
 * applies the accepted entries through a real Workspace.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import { ToolError, Workspace } from "./tools";

export interface StagedChange {
  /** workspace-relative path with forward slashes, for display */
  relPath: string;
  /** absolute resolved path inside the workspace */
  target: string;
  /** disk content when the file was first staged; undefined = new file */
  before: string | undefined;
  /** staged content */
  after: string;
}

export class OverlayWorkspace extends Workspace {
  /** staged changes keyed by absolute resolved path, in first-touch order */
  private readonly staged = new Map<string, StagedChange>();

  changes(): StagedChange[] {
    return [...this.staged.values()];
  }

  hasChanges(): boolean {
    return this.staged.size > 0;
  }

  protected override fileExists(target: string): boolean {
    return this.staged.has(target) || super.fileExists(target);
  }

  protected override readTextFile(target: string): string {
    const pending = this.staged.get(target);
    return pending !== undefined ? pending.after : super.readTextFile(target);
  }

  protected override candidateFiles(cap: number): string[] {
    const merged = new Set(super.candidateFiles(cap));
    for (const target of this.staged.keys()) {
      merged.add(target);
    }
    return [...merged];
  }

  private stage(relPath: string, target: string, after: string): void {
    const existing = this.staged.get(target);
    if (existing) {
      existing.after = after; // keep the original on-disk `before`
      return;
    }
    const before = super.fileExists(target) ? super.readTextFile(target) : undefined;
    this.staged.set(target, {
      relPath: path.relative(this.root, target).split(path.sep).join("/"),
      target,
      before,
      after,
    });
  }

  override writeFile(relPath: string, content: string): string {
    const target = this.resolve(relPath);
    if (!this.staged.has(target) && fs.existsSync(target) && !fs.statSync(target).isFile()) {
      throw new ToolError(`Not a regular file: ${relPath}`);
    }
    this.stage(relPath, target, content);
    return `Staged ${content.length} characters for ${relPath} (applied after user review)`;
  }

  override editFile(relPath: string, oldString: string, newString: string, replaceAll = false): string {
    // prepareEdit validates against the overlay (this.readTextFile), so
    // consecutive edits to the same file compose correctly.
    const { target, updated } = this.prepareEdit(relPath, oldString, newString, replaceAll);
    this.stage(relPath, target, updated);
    return `Staged edit for ${relPath} (applied after user review)`;
  }
}
