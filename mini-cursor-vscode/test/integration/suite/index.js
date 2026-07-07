const vscode = require("vscode");
const assert = require("assert");

exports.run = async function run() {
  const ext = vscode.extensions.getExtension("tythanai.mini-cursor");
  assert.ok(ext, "extension should be discoverable by id tythanai.mini-cursor");

  await ext.activate();
  assert.strictEqual(ext.isActive, true, "extension should report active after activate()");

  const commands = await vscode.commands.getCommands(true);
  const expected = [
    "miniCursor.openChat",
    "miniCursor.newSession",
    "miniCursor.undo",
    "miniCursor.showCheckpoints",
    "miniCursor.compact",
    "miniCursor.showContext",
    "miniCursor.audit",
    "miniCursor.toggleYolo",
    "miniCursor.setApiKey",
    "miniCursor.toggleInlineCompletion",
  ];
  for (const cmd of expected) {
    assert.ok(commands.includes(cmd), `expected command "${cmd}" to be registered`);
  }

  // The chat webview view should be resolvable without throwing: open it via
  // the view container and give it a moment to resolve.
  await vscode.commands.executeCommand("workbench.view.extension.mini-cursor");
  await new Promise((resolve) => setTimeout(resolve, 500));

  console.log("MINI_CURSOR_INTEGRATION_SMOKE_OK");
};
