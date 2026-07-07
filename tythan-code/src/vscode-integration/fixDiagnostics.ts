/**
 * "Fix Problems with AI" — collects the current file's diagnostics (from
 * whatever linters/language servers are active) and sends them into the chat
 * agent as one message, with the file attached via @mention. The agent then
 * reads the file, proposes edits through the normal confirmed-diff flow, and
 * the fixes land as an undoable checkpoint like any other turn.
 *
 * Also exposed as a Quick Fix (lightbulb) code action on any diagnostic, so
 * "AI, fix this" is one click away right where the squiggle is.
 */

import * as vscode from "vscode";

import type { ChatViewProvider } from "./chatPanel";

const MAX_DIAGNOSTICS = 25;

function formatDiagnostic(d: vscode.Diagnostic): string {
  const code = typeof d.code === "object" ? d.code.value : d.code;
  const source = [d.source, code].filter(Boolean).join(" ");
  const tag = source ? ` [${source}]` : "";
  return `- line ${d.range.start.line + 1}${tag}: ${d.message.replace(/\s+/g, " ").trim()}`;
}

export async function fixDiagnostics(
  chatView: ChatViewProvider,
  uri?: vscode.Uri,
  picked?: vscode.Diagnostic[],
): Promise<void> {
  const targetUri = uri ?? vscode.window.activeTextEditor?.document.uri;
  if (!targetUri) {
    void vscode.window.showInformationMessage("Tythan Code: open a file first");
    return;
  }

  const diagnostics = (picked && picked.length > 0 ? picked : vscode.languages.getDiagnostics(targetUri)).filter(
    (d) => d.severity === vscode.DiagnosticSeverity.Error || d.severity === vscode.DiagnosticSeverity.Warning,
  );
  if (diagnostics.length === 0) {
    void vscode.window.showInformationMessage("Tythan Code: no errors or warnings in this file");
    return;
  }

  const rel = vscode.workspace.asRelativePath(targetUri, false);
  const shown = diagnostics.slice(0, MAX_DIAGNOSTICS);
  const omitted = diagnostics.length - shown.length;
  const message =
    `Fix the following problem(s) reported in @${rel}:\n` +
    shown.map(formatDiagnostic).join("\n") +
    (omitted > 0 ? `\n(plus ${omitted} more — fix the listed ones first)` : "") +
    `\n\nRead the file, fix every listed problem with minimal edits, and keep the behavior unchanged.`;

  await vscode.commands.executeCommand("tythanCode.chatView.focus");
  if (!chatView.sendUserMessage(message)) {
    void vscode.window.showWarningMessage("Tythan Code: the agent is busy — try again when the current turn finishes");
  }
}

export class TythanCodeQuickFixProvider implements vscode.CodeActionProvider {
  static readonly metadata: vscode.CodeActionProviderMetadata = {
    providedCodeActionKinds: [vscode.CodeActionKind.QuickFix],
  };

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const relevant = context.diagnostics.filter(
      (d) => d.severity === vscode.DiagnosticSeverity.Error || d.severity === vscode.DiagnosticSeverity.Warning,
    );
    if (relevant.length === 0) {
      return [];
    }
    const action = new vscode.CodeAction("Fix with Tythan Code", vscode.CodeActionKind.QuickFix);
    action.command = {
      command: "tythanCode.fixDiagnostics",
      title: "Fix with Tythan Code",
      arguments: [document.uri, relevant],
    };
    return [action];
  }
}
