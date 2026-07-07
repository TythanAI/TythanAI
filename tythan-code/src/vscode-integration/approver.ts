/**
 * Confirmation UI for mutating tool calls, built on VS Code's native diff
 * editor and modal dialogs rather than a custom webview — this gives users
 * the real side-by-side diff view they already know, and keeps the
 * confirm/cancel flow a plain awaited dialog instead of a hand-rolled
 * request/response protocol over postMessage.
 */

import * as path from "node:path";
import * as vscode from "vscode";

import type { DiffPreview, ToolApprover } from "../core/agent";

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  ".ts": "typescript",
  ".tsx": "typescriptreact",
  ".js": "javascript",
  ".jsx": "javascriptreact",
  ".py": "python",
  ".json": "json",
  ".md": "markdown",
  ".html": "html",
  ".css": "css",
  ".go": "go",
  ".rs": "rust",
  ".java": "java",
  ".rb": "ruby",
  ".php": "php",
  ".sh": "shellscript",
  ".yml": "yaml",
  ".yaml": "yaml",
};

function languageForPath(relPath: string): string | undefined {
  return LANGUAGE_BY_EXTENSION[path.extname(relPath).toLowerCase()];
}

function diffTitle(relPath: string): string {
  return `Tythan Code: ${relPath} (proposed change)`;
}

export class VscodeToolApprover implements ToolApprover {
  /** Open the before/after diff without asking anything — flows that run
   * their own accept/skip UI (composer review) build on this. */
  async showDiffPreview(preview: DiffPreview, options?: { preserveFocus?: boolean }): Promise<void> {
    const language = languageForPath(preview.path);
    const [beforeDoc, afterDoc] = await Promise.all([
      vscode.workspace.openTextDocument({ content: preview.before, language }),
      vscode.workspace.openTextDocument({ content: preview.after, language }),
    ]);
    await vscode.commands.executeCommand("vscode.diff", beforeDoc.uri, afterDoc.uri, diffTitle(preview.path), {
      preview: true,
      preserveFocus: options?.preserveFocus ?? false,
    });
  }

  async closePreview(relPath: string): Promise<void> {
    await closeDiffTab(diffTitle(relPath));
  }

  async confirmDiff(preview: DiffPreview): Promise<boolean> {
    await this.showDiffPreview(preview);
    const choice = await vscode.window.showInformationMessage(
      `Tythan Code wants to write to ${preview.path}. Apply this change?`,
      { modal: true },
      "Apply",
    );
    await this.closePreview(preview.path);
    return choice === "Apply";
  }

  async confirmCommand(command: string): Promise<boolean> {
    const choice = await vscode.window.showWarningMessage(
      `Tythan Code wants to run this command in your workspace:\n\n${command}`,
      { modal: true },
      "Run",
    );
    return choice === "Run";
  }
}

/** Best-effort: close the preview diff once the user has decided, so a long
 * agent turn doesn't leave a trail of stale "proposed change" tabs behind. */
async function closeDiffTab(title: string): Promise<void> {
  try {
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        if (tab.label === title) {
          await vscode.window.tabGroups.close(tab);
          return;
        }
      }
    }
  } catch {
    // Leaving the tab open is harmless; never fail the approval over it.
  }
}
