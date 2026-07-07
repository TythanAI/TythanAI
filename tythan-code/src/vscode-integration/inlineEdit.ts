/**
 * Inline edit — the Cmd/Ctrl+K-style flow: select code (or just place the
 * cursor), describe the change, and the model rewrites exactly that region.
 * The proposed change is shown in VS Code's diff editor and applied only on
 * confirmation, through the normal editor edit path (so plain editor undo
 * reverts it).
 */

import * as vscode from "vscode";

import type { Backend } from "../core/providers/types";
import { VscodeToolApprover } from "./approver";
import { stripFence } from "./inlineCompletion";

// How much of the file around the selection the model gets to see.
const CONTEXT_LINES = 120;

// Generous output cap: an inline edit can legitimately rewrite a large
// selection, unlike the small summary/tab-completion calls.
const EDIT_MAX_TOKENS = 8192;

const EDIT_SYSTEM_PROMPT = `You are an expert code editor embedded in an IDE. You are given an excerpt of \
a source file: the code before a selection (CONTEXT_BEFORE), the selected \
code (SELECTED — may be empty), and the code after it (CONTEXT_AFTER), plus \
an instruction describing the change the user wants.

Reply with ONLY the code that should replace SELECTED — no explanation, no \
markdown code fences, no repetition of the surrounding context. Match the \
file's existing style and indentation. If SELECTED is empty, reply with the \
code to insert at that position. If the instruction cannot be applied to \
this code, reply with SELECTED unchanged.`;

function buildEditPrompt(
  languageId: string,
  relPath: string,
  before: string,
  selected: string,
  after: string,
  instruction: string,
): string {
  return (
    `Language: ${languageId}\nFile: ${relPath}\n\n` +
    `<CONTEXT_BEFORE>\n${before}\n</CONTEXT_BEFORE>\n` +
    `<SELECTED>\n${selected}\n</SELECTED>\n` +
    `<CONTEXT_AFTER>\n${after}\n</CONTEXT_AFTER>\n\n` +
    `Instruction: ${instruction}`
  );
}

export async function editSelection(getBackend: () => Backend | undefined): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    void vscode.window.showInformationMessage("Tythan Code: open a file first");
    return;
  }
  const backend = getBackend();
  if (!backend) {
    void vscode.window.showErrorMessage("Tythan Code: no provider configured — open a folder and set an API key");
    return;
  }

  const document = editor.document;
  const selection = editor.selection;
  const instruction = await vscode.window.showInputBox({
    title: selection.isEmpty ? "Tythan Code: generate code at cursor" : "Tythan Code: edit selection",
    prompt: selection.isEmpty
      ? "Describe the code to insert at the cursor"
      : "Describe how to change the selected code",
    placeHolder: "e.g. add error handling, convert to async, extract a helper…",
    ignoreFocusOut: true,
  });
  if (!instruction?.trim()) {
    return;
  }

  const selected = document.getText(selection);
  const beforeStart = new vscode.Position(Math.max(0, selection.start.line - CONTEXT_LINES), 0);
  const afterEndLine = Math.min(document.lineCount - 1, selection.end.line + CONTEXT_LINES);
  const before = document.getText(new vscode.Range(beforeStart, selection.start));
  const after = document.getText(new vscode.Range(selection.end, document.lineAt(afterEndLine).range.end));
  const relPath = vscode.workspace.asRelativePath(document.uri, false);

  let completion: string | undefined;
  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Tythan Code: generating edit…",
        cancellable: true,
      },
      async (_progress, token) => {
        const abort = new AbortController();
        const cancelListener = token.onCancellationRequested(() => abort.abort());
        try {
          completion = await backend.completeText(
            EDIT_SYSTEM_PROMPT,
            buildEditPrompt(document.languageId, relPath, before, selected, after, instruction),
            { maxTokens: EDIT_MAX_TOKENS, signal: abort.signal },
          );
        } catch (err) {
          if (!token.isCancellationRequested) {
            throw err;
          }
          completion = undefined; // user cancelled — swallow the abort error
        } finally {
          cancelListener.dispose();
        }
      },
    );
  } catch (err) {
    void vscode.window.showErrorMessage(`Tythan Code: edit failed — ${(err as Error).message}`);
    return;
  }
  if (completion === undefined) {
    return; // cancelled
  }

  const replacement = stripFence(completion);
  if (!replacement && !selection.isEmpty) {
    void vscode.window.showInformationMessage("Tythan Code: the model returned an empty edit — nothing applied");
    return;
  }
  if (replacement === selected) {
    void vscode.window.showInformationMessage("Tythan Code: the model proposed no change");
    return;
  }

  // Confirm with a whole-file before/after diff so the change is seen in
  // context, then apply through the editor (native undo covers it).
  const fullBefore = document.getText();
  const fullAfter =
    document.getText(new vscode.Range(new vscode.Position(0, 0), selection.start)) +
    replacement +
    document.getText(new vscode.Range(selection.end, document.lineAt(document.lineCount - 1).range.end));
  const approved = await new VscodeToolApprover().confirmDiff({ path: relPath, before: fullBefore, after: fullAfter });
  if (!approved) {
    return;
  }
  const applied = await editor.edit((builder) => {
    if (selection.isEmpty) {
      builder.insert(selection.active, replacement);
    } else {
      builder.replace(selection, replacement);
    }
  });
  if (!applied) {
    void vscode.window.showErrorMessage("Tythan Code: couldn't apply the edit (the document may have changed)");
  }
}
