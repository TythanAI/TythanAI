/**
 * The chat sidebar: a WebviewView that renders the conversation and forwards
 * typed messages to the agent. Implements AgentSink directly, so Agent.runTurn
 * can stream straight into the webview with no intermediate buffering layer.
 */

import * as crypto from "node:crypto";
import * as vscode from "vscode";

import type { Agent, AgentSink } from "../core/agent";
import type { TranscriptEntry } from "../core/sessionStore";
import { MAX_ENTRY_CHARS, MAX_TRANSCRIPT_ENTRIES } from "../core/sessionStore";
import { runTurnSafely } from "./runTurnSafely";

type OutgoingMessage =
  | { type: "assistantStart" }
  | { type: "user"; text: string }
  | { type: "text"; chunk: string }
  | { type: "thinking" }
  | { type: "flush" }
  | { type: "toolCall"; name: string; input: unknown }
  | { type: "toolResult"; output: string; isError: boolean }
  | { type: "info"; message: string }
  | { type: "error"; message: string }
  | { type: "banner"; workspace: string; backend: string; yolo: boolean }
  | { type: "busy"; value: boolean }
  | { type: "prefill"; text: string }
  | { type: "cleared" };

interface IncomingMessage {
  type: "send" | "ready" | "clear" | "stop" | "insertCode" | "copyCode";
  text?: string;
  code?: string;
}

export class ChatViewProvider implements vscode.WebviewViewProvider, AgentSink {
  static readonly viewType = "tythanCode.chatView";

  private view: vscode.WebviewView | undefined;
  private queue: OutgoingMessage[] = [];
  private ready = false;
  private busyNow = false;

  // Display transcript — the authoritative record the webview is a view of.
  // Rebuilding the webview (sidebar closed/reopened, editor restart with a
  // persisted session) replays this rather than losing the conversation.
  private transcript: TranscriptEntry[] = [];
  private pendingAssistant: string | null = null;

  /** Extra stop hook, so Stop also aborts auxiliary agents (composer). */
  extraStop: (() => void) | undefined;

  /** Called after anything that changes the persisted session (a finished
   * turn, a cleared session) — the extension saves the SessionStore here. */
  onSessionChanged: (() => void) | undefined;

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
        // The transcript replay below covers everything queued while the
        // view was closed — keep only messages replay can't reproduce.
        this.queue = this.queue.filter((m) => m.type === "prefill");
        this.post({ type: "banner", ...this.describeBanner() });
        this.replayTranscript();
        this.post({ type: "busy", value: this.busyNow });
        this.flushQueue();
        return;
      }
      if (message.type === "clear") {
        this.newSession();
        return;
      }
      if (message.type === "stop") {
        this.stopGeneration();
        return;
      }
      if (message.type === "insertCode" && typeof message.code === "string") {
        void insertIntoEditor(message.code);
        return;
      }
      if (message.type === "copyCode" && typeof message.code === "string") {
        void vscode.env.clipboard.writeText(message.code);
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
      this.transcript = [];
      this.pendingAssistant = null;
      this.post({ type: "cleared" });
      this.onSessionChanged?.();
    } catch (err) {
      this.error((err as Error).message);
    }
  }

  /** Abort the in-flight turn, if any. */
  stopGeneration(): void {
    try {
      this.getAgent().stop();
    } catch {
      // no agent (no folder open) — nothing to stop
    }
    this.extraStop?.();
  }

  /** Restore a persisted transcript (rendered on the next webview "ready"). */
  setTranscript(entries: TranscriptEntry[]): void {
    this.transcript = [...entries];
  }

  getTranscript(): TranscriptEntry[] {
    return [...this.transcript];
  }

  /** Toggle the input's busy state — used by flows that drive the agent
   * outside handleUserMessage (composer). */
  setBusy(value: boolean): void {
    this.busyNow = value;
    this.post({ type: "busy", value });
  }

  /** Re-send the banner (workspace / backend / yolo) — call after anything
   * it displays changes, e.g. the YOLO toggle or a provider rebuild. Only
   * posts to a live webview: a not-yet-ready view fetches a fresh banner on
   * "ready" anyway, and queuing a stale one would overwrite it. */
  refreshBanner(): void {
    if (this.ready) {
      this.post({ type: "banner", ...this.describeBanner() });
    }
  }

  /** Put text into the chat input box (appending to whatever is there) and
   * focus it — used by "Add Selection to Chat". */
  prefillInput(text: string): void {
    this.post({ type: "prefill", text });
  }

  private async handleUserMessage(text: string): Promise<void> {
    this.pushEntry({ kind: "user", text });
    this.setBusy(true);
    try {
      const agent = this.getAgent(); // may throw synchronously (e.g. no folder open)
      await runTurnSafely(agent, this, text);
    } catch (err) {
      this.error((err as Error).message);
    } finally {
      this.setBusy(false);
      this.onSessionChanged?.();
    }
  }

  private post(message: OutgoingMessage): void {
    if (this.view && this.ready) {
      void this.view.webview.postMessage(message);
    } else if (message.type === "prefill") {
      // Everything else is reconstructed from the transcript on "ready";
      // a prefill isn't part of the transcript, so keep it for the flush.
      this.queue.push(message);
    }
  }

  private flushQueue(): void {
    for (const message of this.queue) {
      void this.view?.webview.postMessage(message);
    }
    this.queue = [];
  }

  private pushEntry(entry: TranscriptEntry): void {
    this.transcript.push({ ...entry, text: entry.text.slice(0, MAX_ENTRY_CHARS) });
    if (this.transcript.length > MAX_TRANSCRIPT_ENTRIES) {
      this.transcript.splice(0, this.transcript.length - MAX_TRANSCRIPT_ENTRIES);
    }
  }

  private closePendingAssistant(): void {
    if (this.pendingAssistant !== null && this.pendingAssistant !== "") {
      this.pushEntry({ kind: "assistant", text: this.pendingAssistant });
    }
    this.pendingAssistant = null;
  }

  private replayTranscript(): void {
    for (const entry of this.transcript) {
      switch (entry.kind) {
        case "user":
          this.post({ type: "user", text: entry.text });
          break;
        case "assistant":
          this.post({ type: "assistantStart" });
          this.post({ type: "text", chunk: entry.text });
          this.post({ type: "flush" });
          break;
        case "toolCall":
          this.post({ type: "toolCall", name: entry.name ?? "tool", input: entry.text });
          break;
        case "toolResult":
          this.post({ type: "toolResult", output: entry.text, isError: entry.isError ?? false });
          break;
        case "info":
          this.post({ type: "info", message: entry.text });
          break;
        case "error":
          this.post({ type: "error", message: entry.text });
          break;
      }
    }
    // A turn streaming right now: re-open the partial assistant message so
    // subsequent chunks keep appending to it.
    if (this.pendingAssistant !== null) {
      this.post({ type: "assistantStart" });
      if (this.pendingAssistant) {
        this.post({ type: "text", chunk: this.pendingAssistant });
      }
    }
  }

  // -- AgentSink ----------------------------------------------------------

  assistantPrefix(): void {
    this.closePendingAssistant();
    this.pendingAssistant = "";
    this.post({ type: "assistantStart" });
  }
  streamText(chunk: string): void {
    this.pendingAssistant = (this.pendingAssistant ?? "") + chunk;
    this.post({ type: "text", chunk });
  }
  thinkingStarted(): void {
    this.post({ type: "thinking" });
  }
  flushStream(): void {
    this.closePendingAssistant();
    this.post({ type: "flush" });
  }
  toolCall(name: string, input: Record<string, unknown>): void {
    let preview: string;
    try {
      preview = JSON.stringify(input);
    } catch {
      preview = String(input);
    }
    this.pushEntry({ kind: "toolCall", name, text: preview });
    this.post({ type: "toolCall", name, input });
  }
  toolResult(output: string, isError: boolean): void {
    this.pushEntry({ kind: "toolResult", text: output, isError });
    this.post({ type: "toolResult", output, isError });
  }
  info(message: string): void {
    this.pushEntry({ kind: "info", text: message });
    this.post({ type: "info", message });
  }
  error(message: string): void {
    this.pushEntry({ kind: "error", text: message });
    this.post({ type: "error", message });
  }
}

async function insertIntoEditor(code: string): Promise<void> {
  // The webview has focus when the button is clicked, so activeTextEditor is
  // often undefined — fall back to the first visible editor.
  const editor = vscode.window.activeTextEditor ?? vscode.window.visibleTextEditors[0];
  if (!editor) {
    void vscode.window.showWarningMessage("Tythan Code: open a file to insert code into");
    return;
  }
  await editor.edit((builder) => {
    if (editor.selection.isEmpty) {
      builder.insert(editor.selection.active, code);
    } else {
      builder.replace(editor.selection, code);
    }
  });
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
  .code-block {
    margin: 6px 0;
    border: 1px solid var(--vscode-panel-border);
    border-radius: 3px;
    overflow: hidden;
    white-space: normal;
  }
  .code-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 6px;
    font-size: 0.8em;
    color: var(--vscode-descriptionForeground);
    background: var(--vscode-textCodeBlock-background);
    border-bottom: 1px solid var(--vscode-panel-border);
  }
  .code-head .lang { flex: 1; }
  .code-head button {
    padding: 1px 8px;
    font-size: 1em;
    background: transparent;
    color: var(--vscode-textLink-foreground);
  }
  .code-head button:hover { background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.2)); }
  .code-block pre {
    margin: 0;
    padding: 6px 8px;
    overflow-x: auto;
    font-family: var(--vscode-editor-font-family);
    font-size: 0.9em;
    background: var(--vscode-textCodeBlock-background);
    white-space: pre;
  }
  #stop { background: var(--vscode-errorForeground); color: var(--vscode-button-foreground); }
  .hidden { display: none !important; }
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
    <textarea id="input" rows="2" placeholder="Ask Tythan Code... (@file to attach)"></textarea>
    <button id="send">Send</button>
    <button id="stop" class="hidden" title="Stop generating">Stop</button>
  </div>
<script nonce="__NONCE__">
(function () {
  const vscode = acquireVsCodeApi();
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const stopBtn = document.getElementById('stop');
  const bannerEl = document.getElementById('banner');

  let currentAssistantEl = null;
  let currentAssistantRaw = '';
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

  function makeCodeBlock(lang, code) {
    const wrap = document.createElement('div');
    wrap.className = 'code-block';
    const head = document.createElement('div');
    head.className = 'code-head';
    const langEl = document.createElement('span');
    langEl.className = 'lang';
    langEl.textContent = lang || 'code';
    const copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'copyCode', code });
      copyBtn.textContent = 'Copied';
      setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1200);
    });
    const insertBtn = document.createElement('button');
    insertBtn.textContent = 'Insert';
    insertBtn.title = 'Insert at cursor in the active editor';
    insertBtn.addEventListener('click', () => vscode.postMessage({ type: 'insertCode', code }));
    head.appendChild(langEl);
    head.appendChild(copyBtn);
    head.appendChild(insertBtn);
    const pre = document.createElement('pre');
    pre.textContent = code;
    wrap.appendChild(head);
    wrap.appendChild(pre);
    return wrap;
  }

  // Renders assistant text with fenced code blocks (\`\`\`lang ... \`\`\`)
  // as styled blocks with Copy/Insert actions. Everything is added via
  // textContent/createTextNode — no HTML injection surface.
  function renderAssistant(el, raw) {
    el.textContent = '';
    const parts = raw.split('\\u0060\\u0060\\u0060');
    for (let i = 0; i < parts.length; i++) {
      const seg = parts[i];
      if (i % 2 === 0) {
        if (seg) el.appendChild(document.createTextNode(seg));
        continue;
      }
      const nl = seg.indexOf('\\n');
      const lang = nl === -1 ? seg.trim() : seg.slice(0, nl).trim();
      const code = nl === -1 ? '' : seg.slice(nl + 1).replace(/\\n$/, '');
      el.appendChild(makeCodeBlock(lang, code));
    }
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    inputEl.disabled = value;
    sendBtn.classList.toggle('hidden', value);
    stopBtn.classList.toggle('hidden', !value);
  }

  stopBtn.addEventListener('click', () => vscode.postMessage({ type: 'stop' }));

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
      case 'user':
        appendMessage('user', msg.text);
        break;
      case 'assistantStart':
        currentAssistantEl = appendMessage('assistant', '');
        currentAssistantRaw = '';
        break;
      case 'text':
        if (!currentAssistantEl) { currentAssistantEl = appendMessage('assistant', ''); currentAssistantRaw = ''; }
        currentAssistantRaw += msg.chunk;
        renderAssistant(currentAssistantEl, currentAssistantRaw);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;
      case 'thinking':
        if (!currentAssistantEl) { currentAssistantEl = appendMessage('assistant', ''); currentAssistantRaw = ''; }
        break;
      case 'flush':
        currentAssistantEl = null;
        currentAssistantRaw = '';
        break;
      case 'toolCall': {
        const div = document.createElement('div');
        div.className = 'tool-call';
        let preview;
        if (typeof msg.input === 'string') { preview = msg.input; }
        else { try { preview = JSON.stringify(msg.input); } catch (e) { preview = String(msg.input); } }
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
      case 'prefill':
        inputEl.value = (inputEl.value.trim() ? inputEl.value.replace(/\\s+$/, '') + '\\n' : '') + msg.text;
        inputEl.focus();
        break;
      case 'cleared':
        messagesEl.innerHTML = '';
        currentAssistantEl = null;
        currentAssistantRaw = '';
        break;
    }
  });

  vscode.postMessage({ type: 'ready' });
}());
</script>
</body>
</html>
`;
