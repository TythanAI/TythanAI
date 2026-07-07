/**
 * "Generate Commit Message" — reads the repo's staged diff (falling back to
 * the working-tree diff when nothing is staged) through VS Code's built-in
 * Git extension API, asks the model for a conventional-commits message, and
 * drops it straight into the Source Control input box.
 */

import * as vscode from "vscode";

import type { Backend } from "../core/providers/types";

const MAX_DIFF_CHARS = 30_000;

const COMMIT_SYSTEM_PROMPT = `You write git commit messages. Given a diff, reply with ONLY the commit \
message text — no markdown fences, no commentary. Format: a concise \
imperative subject line (max 72 chars, conventional-commits style like \
"feat:", "fix:", "refactor:" when it fits), then, only if the change is \
non-trivial, a blank line and 1-5 short bullet lines explaining what and why.`;

// Minimal slice of the vscode.git extension API this feature needs.
interface GitInputBox {
  value: string;
}
interface GitRepository {
  inputBox: GitInputBox;
  diff(cached?: boolean): Promise<string>;
}
interface GitAPI {
  repositories: GitRepository[];
}
interface GitExtensionExports {
  getAPI(version: 1): GitAPI;
}

function gitApi(): GitAPI | undefined {
  const ext = vscode.extensions.getExtension<GitExtensionExports>("vscode.git");
  if (!ext?.isActive) {
    return undefined;
  }
  try {
    return ext.exports.getAPI(1);
  } catch {
    return undefined;
  }
}

export async function generateCommitMessage(getBackend: () => Backend | undefined): Promise<void> {
  const backend = getBackend();
  if (!backend) {
    void vscode.window.showErrorMessage("Tythan Code: no provider configured");
    return;
  }
  const api = gitApi();
  const repo = api?.repositories[0];
  if (!repo) {
    void vscode.window.showInformationMessage("Tythan Code: no git repository open");
    return;
  }

  let diff = "";
  let staged = true;
  try {
    diff = await repo.diff(true);
    if (!diff.trim()) {
      staged = false;
      diff = await repo.diff(false);
    }
  } catch (err) {
    void vscode.window.showErrorMessage(`Tythan Code: couldn't read the git diff — ${(err as Error).message}`);
    return;
  }
  if (!diff.trim()) {
    void vscode.window.showInformationMessage("Tythan Code: no changes to describe");
    return;
  }
  if (diff.length > MAX_DIFF_CHARS) {
    diff = diff.slice(0, MAX_DIFF_CHARS) + "\n... [diff truncated]";
  }

  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.SourceControl, title: "Tythan Code: writing commit message…" },
      async () => {
        const message = await backend.completeText(
          COMMIT_SYSTEM_PROMPT,
          `${staged ? "Staged diff" : "Working tree diff (nothing staged)"}:\n\n${diff}`,
          { maxTokens: 500 },
        );
        repo.inputBox.value = message.trim();
      },
    );
  } catch (err) {
    void vscode.window.showErrorMessage(`Tythan Code: commit message failed — ${(err as Error).message}`);
  }
}
