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
import { SessionStore } from "./core/sessionStore";
import { VscodeToolApprover } from "./vscode-integration/approver";
import { ChatViewProvider } from "./vscode-integration/chatPanel";
import { runComposer } from "./vscode-integration/composer";
import { TythanCodeInlineCompletionProvider } from "./vscode-integration/inlineCompletion";
import { editSelection } from "./vscode-integration/inlineEdit";
import {
  currentProviderName,
  inlineCompletionModel,
  resolveAgentConfig,
  resolveEffort,
  resolveProviderConfig,
  setApiKeyForProvider,
} from "./vscode-integration/settings";

const CONFIG_KEYS_TRIGGERING_REBUILD = [
  "tythanCode.provider",
  "tythanCode.model",
  "tythanCode.effort",
  "tythanCode.contextWindow",
  "tythanCode.customBaseUrl",
  "tythanCode.maxOutputTokens",
  "tythanCode.inlineCompletion.model",
];

function activeWorkspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function requireAgent(agent: Agent | undefined): Agent {
  if (!agent) {
    throw new Error("Tythan Code: open a folder first");
  }
  return agent;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  let agent: Agent | undefined;
  let backend: Backend | undefined;
  let completionBackend: Backend | undefined;
  let sessionStore: SessionStore | undefined;

  const chatView = new ChatViewProvider(
    () => requireAgent(agent),
    () => ({
      workspace: activeWorkspaceRoot() ?? "(no folder open)",
      backend: backend?.describe() ?? "(not configured)",
      yolo: agent?.yolo ?? false,
    }),
  );

  chatView.onSessionChanged = () => {
    if (agent && backend && sessionStore) {
      sessionStore.save(backend.describe(), agent.messages, chatView.getTranscript());
    }
  };

  async function rebuild(): Promise<void> {
    const root = activeWorkspaceRoot();
    if (!root) {
      agent = undefined;
      backend = undefined;
      completionBackend = undefined;
      sessionStore = undefined;
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
      // A dedicated (typically smaller/faster) model for tab-completion,
      // same provider + key. Low effort on purpose: latency over depth.
      const completionModel = inlineCompletionModel();
      completionBackend = completionModel
        ? makeBackend({ ...providerConfig, model: completionModel }, { effort: "low", maxTokens: 512 })
        : backend;
      const storageDir = path.join(context.globalStorageUri.fsPath, "checkpoints", workspaceStorageKey(root));
      const checkpointStore = new CheckpointStore(root, storageDir);
      agent = new Agent(agentConfig, chatView, new VscodeToolApprover(), backend, checkpointStore);
      sessionStore = new SessionStore(
        path.join(context.globalStorageUri.fsPath, "sessions", `${workspaceStorageKey(root)}.json`),
      );
    } catch (err) {
      void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      agent = undefined;
      backend = undefined;
      completionBackend = undefined;
      sessionStore = undefined;
    }
    chatView.refreshBanner();
  }

  await rebuild();

  // Restore the previous session for this workspace (provider+model must
  // match — provider-native histories aren't interchangeable).
  if (agent && backend && sessionStore) {
    const restored = sessionStore.load(backend.describe());
    if (restored && (restored.messages.length > 0 || restored.transcript.length > 0)) {
      agent.messages = restored.messages;
      chatView.setTranscript(restored.transcript);
    }
  }

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatView),

    vscode.workspace.onDidChangeWorkspaceFolders(() => void rebuild()),

    vscode.workspace.onDidChangeConfiguration((e) => {
      if (CONFIG_KEYS_TRIGGERING_REBUILD.some((key) => e.affectsConfiguration(key))) {
        void rebuild();
      }
    }),

    vscode.commands.registerCommand("tythanCode.openChat", async () => {
      await vscode.commands.executeCommand("tythanCode.chatView.focus");
    }),

    vscode.commands.registerCommand("tythanCode.newSession", () => {
      chatView.newSession();
    }),

    vscode.commands.registerCommand("tythanCode.stop", () => {
      chatView.stopGeneration();
    }),

    vscode.commands.registerCommand("tythanCode.editSelection", async () => {
      await editSelection(() => backend);
    }),

    vscode.commands.registerCommand("tythanCode.composer", async () => {
      await runComposer({ getAgent: () => requireAgent(agent), getBackend: () => backend, chatView });
    }),

    vscode.commands.registerCommand("tythanCode.addSelectionToChat", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        void vscode.window.showInformationMessage("Tythan Code: open a file first");
        return;
      }
      const document = editor.document;
      const selection = editor.selection;
      const relPath = vscode.workspace.asRelativePath(document.uri, false);
      // Empty selection -> attach the whole file via the @mention mechanism;
      // otherwise embed the exact selected lines so the model sees precisely
      // what the user is pointing at.
      const snippet = selection.isEmpty
        ? `@${relPath}`
        : `${relPath} (lines ${selection.start.line + 1}-${selection.end.line + 1}):\n` +
          "```" + document.languageId + "\n" + document.getText(selection) + "\n```";
      chatView.prefillInput(snippet);
      await vscode.commands.executeCommand("tythanCode.chatView.focus");
    }),

    vscode.commands.registerCommand("tythanCode.selectModel", async () => {
      const cfg = vscode.workspace.getConfiguration("tythanCode");
      const provider = cfg.get<string>("provider", "anthropic");
      const current = cfg.get<string>("model", "");
      const suggestions =
        provider === "anthropic"
          ? ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"]
          : [];
      const customLabel = "$(edit) Enter model id…";
      const items = [...new Set([current, ...suggestions])].filter(Boolean).map((m) => ({
        label: m,
        description: m === current ? "current" : undefined,
      }));
      const picked = await vscode.window.showQuickPick([...items, { label: customLabel, description: undefined }], {
        title: `Tythan Code: model for provider "${provider}"`,
      });
      if (!picked) {
        return;
      }
      let model = picked.label;
      if (model === customLabel) {
        const typed = await vscode.window.showInputBox({
          title: "Tythan Code: model id",
          value: current,
          prompt: `Model id to use with the "${provider}" provider`,
        });
        if (!typed?.trim()) {
          return;
        }
        model = typed.trim();
      }
      if (model !== current) {
        await cfg.update("model", model, vscode.ConfigurationTarget.Global);
      }
    }),

    vscode.commands.registerCommand("tythanCode.undo", async () => {
      try {
        const a = requireAgent(agent);
        const checkpoint = a.checkpoints.undoLast();
        if (!checkpoint) {
          void vscode.window.showInformationMessage("Tythan Code: nothing to undo");
          return;
        }
        const skipped = checkpoint.skippedLarge.length + checkpoint.skippedBinary.length;
        const note = skipped > 0 ? ` (${skipped} large/binary file(s) weren't covered)` : "";
        void vscode.window.showInformationMessage(
          `Tythan Code: reverted ${checkpoint.changes.length} file(s) from "${checkpoint.label}"${note}`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.showCheckpoints", async () => {
      try {
        const a = requireAgent(agent);
        const checkpoints = a.checkpoints.list();
        if (checkpoints.length === 0) {
          void vscode.window.showInformationMessage("Tythan Code: no checkpoints yet");
          return;
        }
        const items = checkpoints.map((cp) => ({
          label: cp.label || "(no description)",
          description: `${cp.changes.length} file(s) — ${new Date(cp.createdAt * 1000).toLocaleTimeString()}`,
        }));
        await vscode.window.showQuickPick(items, { title: "Tythan Code checkpoints (most recent first)" });
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.compact", async () => {
      try {
        const a = requireAgent(agent);
        const compacted = await a.maybeCompact(true);
        if (!compacted) {
          void vscode.window.showInformationMessage("Tythan Code: nothing worth compacting yet");
        }
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.showContext", () => {
      try {
        const a = requireAgent(agent);
        const used = a.contextTokensEstimate();
        const budget = a.tokenBudget();
        const pct = budget ? Math.round((100 * used) / budget) : 0;
        void vscode.window.showInformationMessage(
          `Tythan Code context: ~${used} / ${budget} tokens in use (${pct}%) — window ${a.backend.contextWindow}`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.audit", async () => {
      try {
        const a = requireAgent(agent);
        const findings = scanWorkspace(a.workspace);
        const report = formatFindings(findings);
        const doc = await vscode.workspace.openTextDocument({ content: report, language: "plaintext" });
        await vscode.window.showTextDocument(doc, { preview: true });
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.toggleYolo", () => {
      try {
        const a = requireAgent(agent);
        a.yolo = !a.yolo;
        chatView.refreshBanner();
        void vscode.window.showInformationMessage(
          a.yolo
            ? "Tythan Code: auto-approve (yolo) ON — writes/edits/commands run without confirmation"
            : "Tythan Code: confirmations back on",
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`Tythan Code: ${(err as Error).message}`);
      }
    }),

    vscode.commands.registerCommand("tythanCode.setApiKey", async () => {
      const provider = currentProviderName();
      const key = await vscode.window.showInputBox({
        title: `Tythan Code: API key for "${provider}"`,
        password: true,
        ignoreFocusOut: true,
        placeHolder: "sk-...",
      });
      if (!key) {
        return;
      }
      await setApiKeyForProvider(context, provider, key);
      await rebuild();
      void vscode.window.showInformationMessage(`Tythan Code: API key saved for "${provider}"`);
    }),

    vscode.commands.registerCommand("tythanCode.toggleInlineCompletion", async () => {
      const cfg = vscode.workspace.getConfiguration("tythanCode");
      const current = cfg.get<boolean>("inlineCompletion.enabled", true);
      await cfg.update("inlineCompletion.enabled", !current, vscode.ConfigurationTarget.Global);
      void vscode.window.showInformationMessage(`Tythan Code: inline completion ${!current ? "enabled" : "disabled"}`);
    }),

    vscode.languages.registerInlineCompletionItemProvider(
      { pattern: "**" },
      new TythanCodeInlineCompletionProvider(() => completionBackend),
    ),
  );
}

export function deactivate(): void {
  // Nothing to clean up explicitly — all disposables are registered on
  // context.subscriptions and VS Code disposes them automatically.
}
