/**
 * The chat sidebar: a WebviewView that renders the conversation and forwards
 * typed messages to the agent. Implements AgentSink directly, so Agent.runTurn
 * can stream straight into the webview with no intermediate buffering layer.
 */

import * as crypto from "node:crypto";
import * as vscode from "vscode";

import type { Agent, AgentSink } from "../core/agent";
import { runTurnSafely } from "./runTurnSafely";

type OutgoingMessage =
  | { type: "assistantStart" }
  | { type: "text"; chunk: string }
  | { type: "thinking" }
  | { type: "flush" }
  | { type: "toolCall"; name: string; input: unknown }
  | { type: "toolResult"; output: string; isError: boolean }
  | { type: "info"; message: string }
  | { type: "error"; message: string }
  | { type: "banner"; workspace: string; backend: string; yolo: boolean }
  | { type: "busy"; value: boolean }
  | { type: "cleared" };

interface IncomingMessage {
  type: "send" | "ready" | "clear";
  text?: string;
}

export class ChatViewProvider implements vscode.WebviewViewProvider, AgentSink {
  static readonly viewType = "miniCursor.chatView";

  private view: vscode.WebviewView | undefined;
  private queue: OutgoingMessage[] = [];
  private ready = false;

  constructor(
    private readonly getAgent: () => Agent,
    private readonly describeBanner: () => { workspace: string; backend: string; yolo: boolean },
  ) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    this.ready = false;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = renderHtml(webviewView.webview);

    webviewView.webview.onDidReceiveMessage((message: IncomingMessage) => {
      if (message.type === "ready") {
        this.ready = true;
        this.post({ type: "banner", ...this.describeBanner() });
        this.flushQueue();
        return;
      }
      if (message.type === "clear") {
        this.newSession();
        return;
      }
      if (message.type === "send" && message.text?.trim()) {
        void this.handleUserMessage(message.text);
      }
    });

    webviewView.onDidDispose(() => {
      this.view = undefined;
      this.ready = false;
    });
  }

  newSession(): void {
    try {
      this.getAgent().reset();
      this.post({ type: "cleared" });
    } catch (err) {
      this.error((err as Error).message);
    }
  }

  private async handleUserMessage(text: string): Promise<void> {
    this.post({ type: "busy", value: true });
    try {
      const agent = this.getAgent(); // may throw synchronously (e.g. no folder open)
      await runTurnSafely(agent, this, text);
    } catch (err) {
      this.error((err as Error).message);
    } finally {
      this.post({ type: "busy", value: false });
    }
  }

  private post(message: OutgoingMessage): void {
    if (this.view && this.ready) {
      void this.view.webview.postMessage(message);
    } else {
      this.queue.push(message);
    }
  }

  private flushQueue(): void {
    for (const message of this.queue) {
      void this.view?.webview.postMessage(message);
    }
    this.queue = [];
  }

  // -- AgentSink ----------------------------------------------------------

  assistantPrefix(): void {
    this.post({ type: "assistantStart" });
  }
  streamText(chunk: string): void {
    this.post({ type: "text", chunk });
  }
  thinkingStarted(): void {
    this.post({ type: "thinking" });
  }
  flushStream(): void {
    this.post({ type: "flush" });
  }
  toolCall(name: string, input: Record<string, unknown>): void {
    this.post({ type: "toolCall", name, input });
  }
  toolResult(output: string, isError: boolean): void {
    this.post({ type: "toolResult", output, isError });
  }
  info(message: string): void {
    this.post({ type: "info", message });
  }
  error(message: string): void {
    this.post({ type: "error", message });
  }
}

function nonce(): string {
  return crypto.randomBytes(16).toString("hex");
}

function renderHtml(webview: vscode.Webview): string {
  const n = nonce();
  const csp = [`default-src 'none'`, `style-src ${webview.cspSource} 'unsafe-inline'`, `script-src 'nonce-${n}'`].join(
    "; ",
  );
  return PAGE_TEMPLATE.replace(/__CSP__/g, csp).replace(/__NONCE__/g, n);
}

const PAGE_TEMPLATE = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<style>
  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  #banner {
    padding: 6px 10px;
    font-size: 0.85em;
    color: var(--vscode-descriptionForeground);
    border-bottom: 1px solid var(--vscode-panel-border);
  }
  #banner .yolo { color: var(--vscode-errorForeground); font-weight: bold; }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px 10px;
  }
  .msg { margin-bottom: 10px; white-space: pre-wrap; word-break: break-word; }
  .msg.user { color: var(--vscode-foreground); }
  .msg.user::before { content: "you  "; color: var(--vscode-descriptionForeground); font-weight: bold; }
  .msg.assistant::before { content: "assistant  "; color: var(--vscode-textLink-foreground); font-weight: bold; }
  .msg.info { color: var(--vscode-descriptionForeground); font-style: italic; }
  .msg.error { color: var(--vscode-errorForeground); }
  .tool-call {
    margin: 4px 0;
    padding: 4px 8px;
    background: var(--vscode-textCodeBlock-background);
    border-left: 3px solid var(--vscode-textLink-foreground);
    font-family: var(--vscode-editor-font-family);
    font-size: 0.9em;
  }
  .tool-result {
    margin: 2px 0 8px 0;
    padding: 4px 8px;
    font-family: var(--vscode-editor-font-family);
    font-size: 0.85em;
    color: var(--vscode-descriptionForeground);
    max-height: 160px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .tool-result.error { color: var(--vscode-errorForeground); }
  #inputRow {
    display: flex;
    border-top: 1px solid var(--vscode-panel-border);
    padding: 8px;
    gap: 6px;
  }
  #input {
    flex: 1;
    resize: none;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, transparent);
    padding: 6px;
    font-family: inherit;
    font-size: inherit;
  }
  button {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    padding: 0 12px;
    cursor: pointer;
  }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button:disabled { opacity: 0.5; cursor: default; }
</style>
</head>
<body>
  <div id="banner">not connected</div>
  <div id="messages"></div>
  <div id="inputRow">
    <textarea id="input" rows="2" placeholder="Ask mini-cursor... (@file to attach)"></textarea>
    <button id="send">Send</button>
  </div>
<script nonce="__NONCE__">
(function () {
  const vscode = acquireVsCodeApi();
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const bannerEl = document.getElementById('banner');

  let currentAssistantEl = null;
  let busy = false;

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function appendMessage(cls, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    inputEl.disabled = value;
  }

  function send() {
    const text = inputEl.value;
    if (!text.trim() || busy) return;
    appendMessage('user', text);
    inputEl.value = '';
    vscode.postMessage({ type: 'send', text });
  }

  sendBtn.addEventListener('click', send);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  window.addEventListener('message', (event) => {
    const msg = event.data;
    switch (msg.type) {
      case 'banner': {
        bannerEl.innerHTML = escapeHtml(msg.workspace) + '  &middot;  ' + escapeHtml(msg.backend) +
          (msg.yolo ? '  &middot;  <span class="yolo">yolo (no confirmations)</span>' : '');
        break;
      }
      case 'assistantStart':
        currentAssistantEl = appendMessage('assistant', '');
        break;
      case 'text':
        if (!currentAssistantEl) currentAssistantEl = appendMessage('assistant', '');
        currentAssistantEl.textContent += msg.chunk;
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;
      case 'thinking':
        if (!currentAssistantEl) currentAssistantEl = appendMessage('assistant', '');
        break;
      case 'flush':
        currentAssistantEl = null;
        break;
      case 'toolCall': {
        const div = document.createElement('div');
        div.className = 'tool-call';
        let preview;
        try { preview = JSON.stringify(msg.input); } catch (e) { preview = String(msg.input); }
        if (preview && preview.length > 200) preview = preview.slice(0, 200) + '…';
        div.textContent = '⚙ ' + msg.name + ' ' + (preview || '');
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;
      }
      case 'toolResult': {
        const div = document.createElement('div');
        div.className = 'tool-result' + (msg.isError ? ' error' : '');
        const lines = String(msg.output).split('\\n');
        div.textContent = lines.slice(0, 12).join('\\n') + (lines.length > 12 ? '\\n… (' + (lines.length - 12) + ' more lines)' : '');
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;
      }
      case 'info':
        appendMessage('info', msg.message);
        break;
      case 'error':
        appendMessage('error', msg.message);
        break;
      case 'busy':
        setBusy(msg.value);
        break;
      case 'cleared':
        messagesEl.innerHTML = '';
        currentAssistantEl = null;
        break;
    }
  });

  vscode.postMessage({ type: 'ready' });
}());
</script>
</body>
</html>
`;
