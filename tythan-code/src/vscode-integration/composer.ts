/**
 * Composer — Cursor's multi-file editing mode. One task description, the
 * agent plans and edits as many files as needed, and instead of confirming
 * every single write mid-flight, all changes are *staged* into an
 * OverlayWorkspace. At the end the user reviews each file's diff and
 * applies or skips it. Applied files are recorded as one checkpoint, so
 * "Undo Last Agent Change" reverts a whole composer run.
 *
 * run_command is disabled in this mode on purpose: staged changes aren't on
 * disk, so a test run would exercise the *old* code and mislead the model.
 */

import * as vscode from "vscode";

import { Agent } from "../core/agent";
import type { ToolApprover } from "../core/agent";
import { OverlayWorkspace } from "../core/changeset";
import type { StagedChange } from "../core/changeset";
import type { AgentConfig } from "../core/config";
import type { Backend } from "../core/providers/types";
import { VscodeToolApprover } from "./approver";
import type { ChatViewProvider } from "./chatPanel";
import { runTurnSafely } from "./runTurnSafely";

const COMPOSER_PROMPT_EXTRA = `You are running in COMPOSER mode: a multi-file editing session.
- Plan briefly, then make ALL file changes needed to complete the task with
  write_file/edit_file. Changes are staged, not applied: the user reviews
  every file's diff at the end and applies or rejects each one, so do not
  ask for permission between edits.
- read_file/search/list_files see your staged changes, so you can read back
  and refine your own edits.
- run_command is unavailable here (staged changes aren't on disk yet), so
  don't propose running tests — instead double-check your edits by reading
  them back.
- Finish with a short file-by-file summary of what you changed.`;

/** Approver for composer runs: staging is safe (nothing touches disk), so
 * every staged write is allowed without a dialog. Commands stay blocked at
 * the tool level (disabledTools), this is belt-and-suspenders. */
class StagingApprover implements ToolApprover {
  async confirmDiff(): Promise<boolean> {
    return true;
  }
  async confirmCommand(): Promise<boolean> {
    return false;
  }
}

export interface ComposerDeps {
  getAgent: () => Agent;
  getBackend: () => Backend | undefined;
  chatView: ChatViewProvider;
}

export async function runComposer(deps: ComposerDeps): Promise<void> {
  let mainAgent: Agent;
  try {
    mainAgent = deps.getAgent(); // throws when no folder is open
  } catch (err) {
    void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
    return;
  }
  const backend = deps.getBackend();
  if (!backend) {
    void vscode.window.showErrorMessage("Tythan Code: no provider configured");
    return;
  }

  const task = await vscode.window.showInputBox({
    title: "Tythan Code: Composer",
    prompt: "Describe the multi-file change — the agent stages edits and you review every diff at the end",
    placeHolder: "e.g. add a /health endpoint, wire it into the router, and cover it with a test",
    ignoreFocusOut: true,
  });
  if (!task?.trim()) {
    return;
  }

  const overlay = new OverlayWorkspace(mainAgent.workspace.root);
  const composerConfig: AgentConfig = {
    workspaceRoot: mainAgent.workspace.root,
    effort: "high",
    // Only drives the compaction token budget here — the shared backend
    // instance keeps its own output cap from the main configuration.
    maxTokens: 8_192,
    yolo: true, // staging is non-destructive; review happens at the end
    checkpointsEnabled: false, // the apply step records the real checkpoint
    compactKeepRounds: 2,
    systemPromptExtra: COMPOSER_PROMPT_EXTRA,
    disabledTools: ["run_command"],
  };
  const composerAgent = new Agent(
    composerConfig,
    deps.chatView,
    new StagingApprover(),
    backend,
    mainAgent.checkpoints, // inert while checkpointsEnabled=false; the apply step below records the real one
    overlay,
  );

  const chatView = deps.chatView;
  chatView.info(`composer: ${task}`);
  chatView.setBusy(true);
  chatView.extraStop = () => composerAgent.stop();
  await vscode.commands.executeCommand("tythanCode.chatView.focus");
  try {
    await runTurnSafely(composerAgent, chatView, task);
  } finally {
    chatView.extraStop = undefined;
    chatView.setBusy(false);
  }

  const changes = overlay.changes();
  if (changes.length === 0) {
    chatView.info("composer: no file changes were staged");
    return;
  }

  const accepted = await reviewChanges(changes);
  if (accepted === undefined) {
    chatView.info("composer: review cancelled — nothing applied");
    return;
  }
  if (accepted.length === 0) {
    chatView.info("composer: all changes skipped — nothing applied");
    return;
  }

  // Apply through the *real* workspace, recorded as one checkpoint so the
  // whole composer run is undoable with "Undo Last Agent Change".
  mainAgent.checkpoints.beginTurn(`composer: ${task}`);
  const applied: string[] = [];
  const failed: string[] = [];
  for (const change of accepted) {
    try {
      mainAgent.checkpoints.recordBefore(change.target);
    } catch {
      // checkpointing is best-effort; the write below still proceeds
    }
    try {
      mainAgent.workspace.writeFile(change.relPath, change.after);
      applied.push(change.relPath);
    } catch (err) {
      failed.push(`${change.relPath}: ${(err as Error).message}`);
    }
  }
  try {
    mainAgent.checkpoints.commitTurn();
  } catch {
    chatView.error("composer: couldn't save the undo checkpoint for this run");
  }

  if (applied.length > 0) {
    chatView.info(`composer: applied ${applied.length} file(s) — ${applied.join(", ")} (undo reverts all of them)`);
  }
  for (const f of failed) {
    chatView.error(`composer: failed to apply ${f}`);
  }
}

function lineCount(text: string): number {
  return text.length === 0 ? 0 : text.split("\n").length;
}

function describeChange(change: StagedChange): string {
  if (change.before === undefined) {
    return `new file · ${lineCount(change.after)} lines`;
  }
  return `modified · ${lineCount(change.before)} → ${lineCount(change.after)} lines`;
}

interface ReviewItem extends vscode.QuickPickItem {
  change: StagedChange;
}

/** One checkbox list for the whole changeset: every file starts checked,
 * moving the highlight previews that file's diff beside the picker, Enter
 * applies exactly the checked files, Esc applies nothing. */
async function reviewChanges(changes: StagedChange[]): Promise<StagedChange[] | undefined> {
  const approver = new VscodeToolApprover();
  const picker = vscode.window.createQuickPick<ReviewItem>();
  picker.title = `Composer: review ${changes.length} staged file(s) — Enter applies checked, Esc cancels`;
  picker.placeholder = "Uncheck files to skip; highlight a file to preview its diff";
  picker.canSelectMany = true;
  picker.ignoreFocusOut = true;
  picker.items = changes.map((change) => ({
    label: change.relPath,
    description: describeChange(change),
    change,
  }));
  picker.selectedItems = picker.items; // everything accepted by default

  let previewed: string | undefined;
  picker.onDidChangeActive(async (active) => {
    const item = active[0];
    if (!item || item.change.relPath === previewed) {
      return;
    }
    previewed = item.change.relPath;
    // preserveFocus keeps the picker focused while the diff renders behind it.
    await approver.showDiffPreview(
      { path: item.change.relPath, before: item.change.before ?? "", after: item.change.after },
      { preserveFocus: true },
    );
  });

  const accepted = await new Promise<StagedChange[] | undefined>((resolve) => {
    picker.onDidAccept(() => {
      const picked = picker.selectedItems.map((i) => i.change);
      resolve(picked); // before hide(): onDidHide also resolves (undefined) and first wins
      picker.hide();
    });
    picker.onDidHide(() => {
      picker.dispose();
      resolve(undefined);
    });
    picker.show();
  });

  if (previewed !== undefined) {
    await approver.closePreview(previewed);
  }
  return accepted;
}
