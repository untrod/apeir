import * as vscode from "vscode";

const editorActions: Record<string, string> = {
  "nous.explain": "editor.explain",
  "nous.review": "editor.review",
  "nous.optimize": "editor.optimize",
  "nous.refactor": "editor.refactor",
  "nous.generateTests": "editor.tests",
};
const readOnlyActions = new Set(["runtime.status", "run.list", "run.show", "provider.list", "approval.list"]);

export function activate(context: vscode.ExtensionContext) {
  const output = vscode.window.createOutputChannel("Nous Runtime");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand("nous.configureToken", async () => {
    const token = await vscode.window.showInputBox({ prompt: "Nous Runtime token; leave empty to remove", password: true });
    if (token === undefined) return;
    if (token) await context.secrets.store("nous.runtimeToken", token);
    else await context.secrets.delete("nous.runtimeToken");
  }));
  context.subscriptions.push(vscode.commands.registerCommand("nous.openRuntime", () => openPanel(context, output)));
  context.subscriptions.push(vscode.commands.registerCommand("nous.approve", () => resolveApproval(context, output, "approve")));
  context.subscriptions.push(vscode.commands.registerCommand("nous.reject", () => resolveApproval(context, output, "reject")));
  for (const [command, action] of Object.entries(editorActions)) {
    context.subscriptions.push(vscode.commands.registerCommand(command, async () => {
      const editor = vscode.window.activeTextEditor;
      const prompt = editor?.document.getText(editor.selection) || "";
      output.show();
      output.appendLine(await send(context, action, {
        prompt,
        workspace: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "",
      }));
    }));
  }
  context.subscriptions.push(vscode.commands.registerCommand("nous.openTimeline", async () => {
    output.show();
    output.appendLine(await send(context, "run.list", {}));
  }));
}

async function resolveApproval(context: vscode.ExtensionContext, output: vscode.OutputChannel, decision: "approve" | "reject") {
  const requestId = await vscode.window.showInputBox({ prompt: `Approval request ID to ${decision}` });
  if (!requestId) return;
  output.show();
  output.appendLine(await send(context, "approval.resolve", { request_id: requestId, decision }));
}

function openPanel(context: vscode.ExtensionContext, output: vscode.OutputChannel) {
  const panel = vscode.window.createWebviewPanel(
    "nousRuntime",
    "Nous Runtime",
    vscode.ViewColumn.Beside,
    { enableScripts: true },
  );
  panel.webview.html = `<!doctype html><style>body{font-family:var(--vscode-font-family);padding:16px}button{margin:4px;padding:8px}pre{white-space:pre-wrap}</style><h2>NOUS Runtime</h2><div><button data-a="runtime.status">Dashboard</button><button data-a="run.list">Runs</button><button data-a="provider.list">Providers</button><button data-a="approval.list">Approvals</button></div><pre id="result">Runtime panel ready.</pre><script>const vscode=acquireVsCodeApi();document.querySelectorAll('button').forEach(b=>b.onclick=()=>vscode.postMessage({action:b.dataset.a}));window.addEventListener('message',e=>document.getElementById('result').textContent=e.data);</script>`;
  panel.webview.onDidReceiveMessage(async message => {
    await panel.webview.postMessage(await send(context, String(message.action || ""), {}));
  });
  output.appendLine("IDE Runtime panel opened; Server Runtime remains authoritative.");
}

async function send(context: vscode.ExtensionContext, action: string, params: unknown): Promise<string> {
  const base = vscode.workspace.getConfiguration("nous").get<string>("serverUrl", "http://localhost:8770");
  const token = await context.secrets.get("nous.runtimeToken");
  const attempts = readOnlyActions.has(action) ? 2 : 1;
  let lastError = "Runtime unavailable";
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(`${base}/api/ide/runtime`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ action, params }),
      });
      const payload = await response.json() as { ok: boolean; data?: unknown; error?: { message?: string; code?: string } };
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error?.message || payload.error?.code || `HTTP ${response.status}`);
      }
      return JSON.stringify(payload.data, null, 2);
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
      if (attempt + 1 < attempts) await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  return `Runtime request failed: ${lastError}`;
}

export function deactivate() {}