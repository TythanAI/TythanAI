/**
 * Extension entry point: builds the Agent from the active workspace +
 * settings, wires it to the chat webview, registers commands and the inline
 * completion provider. This file is the only place that touches both
 * `vscode` and the core agent construction — everything else either lives in
 * `core/` (vscode-independent) or `vscode-integration/` (thin adapters).
 */

import * as path from "node:path";
import * as vscode from "vscode";

import { Agent } from "./core/agent";
import type { AgentConfig } from "./core/config";
import { CheckpointStore, workspaceStorageKey } from "./core/checkpoints";
import { formatFindings, scanWorkspace } from "./core/security";
import { makeBackend } from "./core/providers";
import type { Backend } from "./core/providers/types";
import { VscodeToolApprover } from "./vscode-integration/approver";
import { ChatViewProvider } from "./vscode-integration/chatPanel";
import { MiniCursorInlineCompletionProvider } from "./vscode-integration/inlineCompletion";
import {
  currentProviderName,
  resolveAgentConfig,
  resolveEffort,
  resolveProviderConfig,
  setApiKeyForProvider,
} from "./vscode-integration/settings";

const CONFIG_KEYS_TRIGGERING_REBUILD = [
  "miniCursor.provider",
  "miniCursor.model",
  "miniCursor.effort",
  "miniCursor.contextWindow",
  "miniCursor.customBaseUrl",
  "miniCursor.maxOutputTokens",
];

function activeWorkspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function requireAgent(agent: Agent | undefined): Agent {
  if (!agent) {
    throw new Error("mini-cursor: open a folder first");
  }
  return agent;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  let agent: Agent | undefined;
  let backend: Backend | undefined;

  const chatView = new ChatViewProvider(
    () => requireAgent(agent),
    () => ({
      workspace: activeWorkspaceRoot() ?? "(no folder open)",
      backend: backend?.describe() ?? "(not configured)",
      yolo: agent?.yolo ?? false,
    }),
  );

  async function rebuild(): Promise<void> {
    const root = activeWorkspaceRoot();
    if (!root) {
      agent = undefined;
      backend = undefined;
      return;
    }
    // Never let a config/backend problem fail activation or leave `agent`
    // pointing at half-built state — worst case, commands report "open a
    // folder first" / show the specific error, rather than the whole
    // extension failing to load.
    try {
      const providerConfig = await resolveProviderConfig(context);
      const agentConfig: AgentConfig = resolveAgentConfig(root);
      backend = makeBackend(providerConfig, { effort: resolveEffort(), maxTokens: agentConfig.maxTokens });
      const storageDir = path.join(context.globalStorageUri.fsPath, "checkpoints", workspaceStorageKey(root));
      const checkpointStore = new CheckpointStore(root, storageDir);
      agent = new Agent(agentConfig, chatView, new VscodeToolApprover(), backend, checkpointStore);
    } catch (err) {
      void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      agent = undefined;
      backend = undefined;
    }
  }

  await rebuild();

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatView),

    vscode.workspace.onDidChangeWorkspaceFolders(() => void rebuild()),

    vscode.workspace.onDidChangeConfiguration((e) => {
      if (CONFIG_KEYS_TRIGGERING_REBUILD.some((key) => e.affectsConfiguration(key))) {
        void rebuild();
      }
    }),

    vscode.commands.registerCommand("miniCursor.openChat", async () => {
      await vscode.commands.executeCommand("miniCursor.chatView.focus");
    }),

    vscode.commands.registerCommand("miniCursor.newSession", () => {
      chatView.newSession();
    }),

    vscode.commands.registerCommand("miniCursor.undo", async () => {
      try {
        const a = requireAgent(agent);
        const checkpoint = a.checkpoints.undoLast();
        if (!checkpoint) {
          void vscode.window.showInformationMessage("mini-cursor: nothing to undo");
          return;
        }
        const skipped = checkpoint.skippedLarge.length + checkpoint.skippedBinary.length;
        const note = skipped > 0 ? ` (${skipped} large/binary file(s) weren't covered)` : "";
        void vscode.window.showInformationMessage(
          `mini-cursor: reverted ${checkpoint.changes.length} file(s) from "${checkpoint.label}"${note}`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.showCheckpoints", async () => {
      try {
        const a = requireAgent(agent);
        const checkpoints = a.checkpoints.list();
        if (checkpoints.length === 0) {
          void vscode.window.showInformationMessage("mini-cursor: no checkpoints yet");
          return;
        }
        const items = checkpoints.map((cp) => ({
          label: cp.label || "(no description)",
          description: `${cp.changes.length} file(s) — ${new Date(cp.createdAt * 1000).toLocaleTimeString()}`,
        }));
        await vscode.window.showQuickPick(items, { title: "mini-cursor checkpoints (most recent first)" });
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.compact", async () => {
      try {
        const a = requireAgent(agent);
        const compacted = await a.maybeCompact(true);
        if (!compacted) {
          void vscode.window.showInformationMessage("mini-cursor: nothing worth compacting yet");
        }
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.showContext", () => {
      try {
        const a = requireAgent(agent);
        const used = a.contextTokensEstimate();
        const budget = a.tokenBudget();
        const pct = budget ? Math.round((100 * used) / budget) : 0;
        void vscode.window.showInformationMessage(
          `mini-cursor context: ~${used} / ${budget} tokens in use (${pct}%) — window ${a.backend.contextWindow}`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.audit", async () => {
      try {
        const a = requireAgent(agent);
        const findings = scanWorkspace(a.workspace);
        const report = formatFindings(findings);
        const doc = await vscode.workspace.openTextDocument({ content: report, language: "plaintext" });
        await vscode.window.showTextDocument(doc, { preview: true });
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.toggleYolo", () => {
      try {
        const a = requireAgent(agent);
        a.yolo = !a.yolo;
        void vscode.window.showInformationMessage(
          a.yolo
            ? "mini-cursor: auto-approve (yolo) ON — writes/edits/commands run without confirmation"
            : "mini-cursor: confirmations back on",
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`mini-cursor: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("miniCursor.setApiKey", async () => {
      const provider = currentProviderName();
      const key = await vscode.window.showInputBox({
        title: `mini-cursor: API key for "${provider}"`,
        password: true,
        ignoreFocusOut: true,
        placeHolder: "sk-...",
      });
      if (!key) {
        return;
      }
      await setApiKeyForProvider(context, provider, key);
      await rebuild();
      void vscode.window.showInformationMessage(`mini-cursor: API key saved for "${provider}"`);
    }),

    vscode.commands.registerCommand("miniCursor.toggleInlineCompletion", async () => {
      const cfg = vscode.workspace.getConfiguration("miniCursor");
      const current = cfg.get<boolean>("inlineCompletion.enabled", true);
      await cfg.update("inlineCompletion.enabled", !current, vscode.ConfigurationTarget.Global);
      void vscode.window.showInformationMessage(`mini-cursor: inline completion ${!current ? "enabled" : "disabled"}`);
    }),

    vscode.languages.registerInlineCompletionItemProvider(
      { pattern: "**" },
      new MiniCursorInlineCompletionProvider(() => backend),
    ),
  );
}

export function deactivate(): void {
  // Nothing to clean up explicitly — all disposables are registered on
  // context.subscriptions and VS Code disposes them automatically.
}
