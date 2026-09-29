const vscode = require("vscode");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execFile } = require("child_process");

const GROUPS = [
  { key: "asking", label: "Asking you", color: "charts.yellow", open: true },
  { key: "check", label: "Check me", color: "charts.red", open: true },
  { key: "active", label: "Working", color: "charts.blue", open: true },
  { key: "yourturn", label: "Your turn", color: "charts.green", open: true },
  { key: "pending", label: "Continue later", color: "charts.purple", open: true },
  { key: "suggested", label: "Suggestions", color: "terminal.ansiCyan", open: false },
  { key: "idle", label: "Idle", color: "disabledForeground", open: false },
  { key: "temporary", label: "Temporary", color: "disabledForeground", open: false },
  { key: "completed", label: "Completed", color: "charts.green", open: false },
];

// The installed app carries the matching service, so prefer it over any
// standalone copy that could be stale.
function appScript() {
  const rel = "Agent Board.app/Contents/Resources/Backend/agent_board.py";
  const found = [path.join(os.homedir(), "Applications", rel), path.join("/Applications", rel)].find((p) => fs.existsSync(p));
  return found || path.join(os.homedir(), "Applications", rel);
}

// The installed app bundle, unless the user points the sidebar at another script.
function appBundle() {
  if (vscode.workspace.getConfiguration("agentBoard").get("scriptPath", "")) return null;
  const app = path.resolve(appScript(), "../../../..");
  return fs.existsSync(app) ? app : null;
}

function appVersion(app) {
  try {
    return fs.readFileSync(path.join(app, "Contents/Resources/Backend/VERSION"), "utf8").trim();
  } catch (e) {
    return null;
  }
}

function cfg() {
  const c = vscode.workspace.getConfiguration("agentBoard");
  return {
    port: c.get("port", 8765),
    script: (c.get("scriptPath", "") || appScript()).replace(/^~(?=\/)/, os.homedir()),
    refresh: Math.max(3, c.get("refreshSeconds", 10)),
  };
}

function request(method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : null;
    const headers = payload ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) } : {};
    const req = http.request({ host: "127.0.0.1", port: cfg().port, path: urlPath, method, headers, timeout: 8000 }, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => (res.statusCode < 400 ? resolve(body) : reject(new Error("HTTP " + res.statusCode))));
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", reject);
    req.end(payload || undefined);
  });
}

function age(sec) {
  const m = Math.max(0, sec / 60);
  if (m < 60) return Math.round(m) + "m";
  if (m < 60 * 24) return Math.round(m / 60) + "h";
  return Math.round(m / 1440) + "d";
}

class Provider {
  constructor() {
    this.data = null;
    this.error = null;
    this.filter = "";
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
  }

  set(data, error) {
    this.data = data;
    this.error = error;
    this._emitter.fire();
  }

  sessions() {
    if (!this.data) return [];
    const f = this.filter.toLowerCase();
    return this.data.sessions.filter((s) => !f || (s.title || "").toLowerCase().includes(f));
  }

  getTreeItem(el) {
    return el;
  }

  getChildren(el) {
    if (!el) {
      if (this.error && !this.data) {
        const item = new vscode.TreeItem("Agent Board is not reachable");
        item.description = "click to retry";
        item.iconPath = new vscode.ThemeIcon("warning");
        item.tooltip = this.error;
        item.command = { command: "agentBoard.refresh", title: "Refresh" };
        return [item];
      }
      if (!this.data) return [new vscode.TreeItem("Loading…")];
      const all = this.sessions();
      return GROUPS.map((g) => ({ g, list: all.filter((s) => s.bucket === g.key) }))
        .filter((x) => x.list.length)
        .map(({ g, list }) => {
          const item = new vscode.TreeItem(
            g.label,
            this.filter || g.open ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed
          );
          item.id = "group:" + g.key + (this.filter ? ":f" : "");
          item.description = String(list.length);
          item.contextValue = "group";
          item.groupKey = g.key;
          return item;
        });
    }
    if (el.contextValue !== "group") return [];
    const g = GROUPS.find((x) => x.key === el.groupKey);
    const now = this.data.now;
    return this.sessions()
      .filter((s) => s.bucket === el.groupKey)
      .sort((a, b) => (b.activity || 0) - (a.activity || 0))
      .map((s) => {
        const item = new vscode.TreeItem(s.title || s.id);
        item.id = "session:" + s.id;
        item.sessionId = s.id;
        item.contextValue = `session;done=${s.completed ? 1 : 0};cont=${s.choice === "continue" ? 1 : 0}`;
        item.description = age(now - (s.activity || s.last_ts || now)) + (s.root === "codex" ? " · Codex" : "") + (s.continued ? " · continued" : "");
        item.iconPath = new vscode.ThemeIcon(s.flag ? "star-full" : "circle-filled", new vscode.ThemeColor(g.color));
        const tip = new vscode.MarkdownString();
        tip.appendMarkdown(`**${(s.title || "").replace(/[*_`]/g, "")}**\n\n`);
        if (s.detail) tip.appendText(s.detail + "\n\n");
        if (s.last_text) tip.appendText(s.last_text + "\n\n");
        tip.appendText(`${s.project || ""} · ${s.root}`);
        item.tooltip = tip;
        item.command = { command: "agentBoard.open", title: "Open session", arguments: [s.id] };
        return item;
      });
  }
}

let startedAt = 0;

function startBoard() {
  if (Date.now() - startedAt < 60000) return;
  startedAt = Date.now();
  const { script, port } = cfg();
  const app = appBundle();
  try {
    // Let the app own its service. Running the bundled Python here writes
    // __pycache__ into the signed app and leaves a copy the updater cannot stop.
    const env = port === 8765 ? [] : ["--env", "AGENT_BOARD_PORT=" + port];
    const child = app
      ? spawn("/usr/bin/open", ["-g", "-j", ...env, app], { detached: true, stdio: "ignore" })
      : spawn("python3", ["-B", script, "--no-open", "--port", String(port)], {
          cwd: path.dirname(script),
          detached: true,
          stdio: "ignore",
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
        });
    child.on("error", () => {});
    child.unref();
  } catch (e) {
    // ignore; the tree shows the error
  }
}

let staleCheckedAt = 0;

// After an app update, a service started from the old bundle can keep the port.
// Stop it only when it runs from inside the installed app, then let the app restart it.
function stopStaleService(running) {
  const app = appBundle();
  const installed = app && appVersion(app);
  if (!installed || !running || running === installed || Date.now() - staleCheckedAt < 300000) return;
  staleCheckedAt = Date.now();
  const inside = path.join(app, "Contents/Resources") + path.sep;
  execFile("/usr/sbin/lsof", ["-nP", `-iTCP:${cfg().port}`, "-sTCP:LISTEN", "-t"], (err, out) => {
    if (err) return;
    for (const pid of out.split(/\s+/).filter((x) => /^\d+$/.test(x))) {
      execFile("/bin/ps", ["-o", "command=", "-p", pid], (e, command) => {
        if (e || !command.includes(inside)) return;
        try {
          process.kill(Number(pid), "SIGTERM");
          startedAt = 0;
        } catch (x) {
          // ignore; the next refresh reports the service state
        }
      });
    }
  });
}

function activate(context) {
  const provider = new Provider();
  const view = vscode.window.createTreeView("agentBoard.sessions", { treeDataProvider: provider });
  context.subscriptions.push(view);

  async function refresh() {
    try {
      const data = JSON.parse(await request("GET", "/api/status"));
      provider.set(data, null);
      stopStaleService(data.version);
      const n = data.sessions.filter((s) => ["asking", "check", "yourturn"].includes(s.bucket)).length;
      view.badge = n ? { value: n, tooltip: `${n} need you` } : undefined;
    } catch (e) {
      startBoard();
      provider.set(provider.data, String(e.message || e));
    }
  }

  let timer;
  function schedule() {
    clearInterval(timer);
    timer = setInterval(() => view.visible && refresh(), cfg().refresh * 1000);
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("agentBoard.refresh", refresh),
    vscode.commands.registerCommand("agentBoard.open", async (id) => {
      try {
        await request("POST", "/api/open?id=" + encodeURIComponent(id));
      } catch (e) {
        vscode.window.showErrorMessage("Could not open session: " + (e.message || e));
      }
    }),
    ...[
      ["agentBoard.markDone", "/api/complete", (id) => ({ id, on: true })],
      ["agentBoard.undoDone", "/api/complete", (id) => ({ id, on: false })],
      ["agentBoard.continueLater", "/api/choice", (id) => ({ id, choice: "continue" })],
      ["agentBoard.clearContinue", "/api/choice", (id) => ({ id, choice: "clear" })],
    ].map(([cmd, urlPath, body]) =>
      vscode.commands.registerCommand(cmd, async (item) => {
        if (!item || !item.sessionId) return;
        try {
          await request("POST", urlPath, body(item.sessionId));
          await refresh();
        } catch (e) {
          vscode.window.showErrorMessage("Agent Board update failed: " + (e.message || e));
        }
      })
    ),
    vscode.commands.registerCommand("agentBoard.resumeNew", async (item) => {
      if (!item || !item.sessionId) return;
      try {
        const res = JSON.parse(await request("POST", "/api/resume-new?id=" + encodeURIComponent(item.sessionId)));
        if (res.mode === "copied") {
          vscode.window.showInformationMessage("Resume prompt copied. Paste it into the new Codex chat.");
        }
      } catch (e) {
        vscode.window.showErrorMessage(
          "Could not start a resume chat. The board service may need the update with Resume in new chat. " + (e.message || e)
        );
      }
    }),
    vscode.commands.registerCommand("agentBoard.openBoard", () =>
      vscode.env.openExternal(vscode.Uri.parse(`http://127.0.0.1:${cfg().port}/`))
    ),
    vscode.commands.registerCommand("agentBoard.search", async () => {
      const q = await vscode.window.showInputBox({ prompt: "Filter sessions by title", value: provider.filter });
      if (q === undefined) return;
      provider.filter = q.trim();
      view.message = provider.filter ? `Filter: ${provider.filter}` : undefined;
      vscode.commands.executeCommand("setContext", "agentBoard.searching", !!provider.filter);
      provider.set(provider.data, provider.error);
    }),
    vscode.commands.registerCommand("agentBoard.clearSearch", () => {
      provider.filter = "";
      view.message = undefined;
      vscode.commands.executeCommand("setContext", "agentBoard.searching", false);
      provider.set(provider.data, provider.error);
    }),
    view.onDidChangeVisibility((e) => e.visible && refresh()),
    vscode.workspace.onDidChangeConfiguration((e) => e.affectsConfiguration("agentBoard") && (schedule(), refresh())),
    { dispose: () => clearInterval(timer) }
  );

  schedule();
  refresh();
}

function deactivate() {}

module.exports = { activate, deactivate };
