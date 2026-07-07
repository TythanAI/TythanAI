const vscode = require("vscode");
const assert = require("assert");

exports.run = async function run() {
  const ext = vscode.extensions.getExtension("tythanai.tythan-code");
  assert.ok(ext, "extension should be discoverable by id tythanai.tythan-code");

  await ext.activate();
  assert.strictEqual(ext.isActive, true, "extension should report active after activate()");

  const commands = await vscode.commands.getCommands(true);
  const expected = [
    "tythanCode.openChat",
    "tythanCode.newSession",
    "tythanCode.undo",
    "tythanCode.showCheckpoints",
    "tythanCode.compact",
    "tythanCode.showContext",
    "tythanCode.audit",
    "tythanCode.toggleYolo",
    "tythanCode.setApiKey",
    "tythanCode.toggleInlineCompletion",
  ];
  for (const cmd of expected) {
    assert.ok(commands.includes(cmd), `expected command "${cmd}" to be registered`);
  }

  // The chat webview view should be resolvable without throwing: open it via
  // the view container and give it a moment to resolve.
  await vscode.commands.executeCommand("workbench.view.extension.tythanCode");
  await new Promise((resolve) => setTimeout(resolve, 500));

  console.log("TYTHAN_CODE_INTEGRATION_SMOKE_OK");
};
