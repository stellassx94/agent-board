const vscode = require("vscode");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
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
// A scriptPath inside the installed app still means the app.
function appBundle() {
  const custom = vscode.workspace.getConfiguration("agentBoard").get("scriptPath", "");
  if (custom && path.resolve(custom.replace(/^~(?=\/)/, os.homedir())) !== appScript()) return null;
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

// The topic view keeps these statuses as groups: the first set above the
// topics, the second below. Every other row is filed under its topic.
const TOPIC_TOP = ["asking", "check", "active", "yourturn"];
const TOPIC_BOTTOM = ["temporary", "completed"];

// Ticket keys such as ABC-1234 that a row mentions, so they show and search.
// agentBoard.ticketPrefixes narrows them; an empty list accepts any prefix.
function tickets(s, prefixes) {
  const text = [s.title, s.detail, s.last_user, s.last_text].filter(Boolean).join(" ");
  const found = text.match(/\b[A-Z][A-Z0-9]{1,9}-\d{2,}\b/g) || [];
  return [...new Set(found)].filter((k) => !prefixes.length || prefixes.includes(k.slice(0, k.lastIndexOf("-"))));
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

  // One row per workstream, like the board's default view, so resumed chats
  // merge into their original row and the counts match the app.
  // Older services without workstreams fall back to one row per session.
  sessions(unfiltered) {
    if (!this.data) return [];
    const f = unfiltered ? "" : this.filter.toLowerCase();
    const byId = new Map(this.data.sessions.map((s) => [s.id, s]));
    const rows = this.data.workstreams
      ? this.data.workstreams.map((w) => {
          const lead = byId.get(w.lead_id) || {};
          return {
            ...lead,
            id: w.latest_id || w.lead_id || w.id,
            workstreamId: w.id,
            leadId: w.lead_id,
            title: w.title,
            topic: w.topic,
            autoTopic: w.auto_topic,
            topicPinned: !!w.topic_pinned,
            bucket: w.bucket,
            activity: w.activity,
            flag: w.flag,
            completed: w.completed || (w.session_count === 1 && !!lead.completed),
            detail: w.detail || lead.detail,
            count: w.session_count || 1,
            codexOnly: (w.roots || []).length > 0 && w.roots.every((r) => r === "codex"),
          };
        })
      : this.data.sessions.map((s) => ({ ...s, leadId: s.id, autoTopic: s.auto_topic, topicPinned: !!s.topic_pinned, count: 1, codexOnly: s.root === "codex" }));
    const prefixes = vscode.workspace.getConfiguration("agentBoard").get("ticketPrefixes", []).map((p) => String(p).toUpperCase());
    return rows
      .map((s) => ({ ...s, topic: s.topic || null, tickets: tickets(s, prefixes) }))
      .filter((s) => !f || ((s.title || "") + " " + s.tickets.join(" ")).toLowerCase().includes(f));
  }

  // Show a group move at once; the next refresh confirms it from the service.
  move(items, topic) {
    if (!this.data) return;
    const ids = new Set(items.map((it) => it.workstreamId || it.sessionId));
    for (const x of [...(this.data.workstreams || []), ...this.data.sessions]) {
      if (!ids.has(x.id) && !(x.workstream_id && ids.has(x.workstream_id))) continue;
      x.topic = topic || x.auto_topic || null;
      x.topic_pinned = !!topic;
    }
    if (topic && !this.topics().includes(topic)) this.data.topics = [...this.topics(), topic];
    this._emitter.fire();
  }

  // Topics come from the board service, so the app and this list agree.
  // Without any, the list stays grouped by status.
  topics() {
    return (this.data && this.data.topics) || [];
  }

  byTopic() {
    return vscode.workspace.getConfiguration("agentBoard").get("groupBy", "status") === "topic" && this.topics().length > 0;
  }

  // Rows filed under topics, most urgent status first.
  topicRows() {
    const order = GROUPS.map((g) => g.key).filter((k) => !TOPIC_TOP.includes(k) && !TOPIC_BOTTOM.includes(k));
    return this.sessions()
      .filter((s) => order.includes(s.bucket))
      .sort((a, b) => order.indexOf(a.bucket) - order.indexOf(b.bucket) || (b.activity || 0) - (a.activity || 0));
  }

  // Status group headers for the given buckets, empty ones left out.
  groups(keys) {
    const all = this.sessions();
    return GROUPS.filter((g) => keys.includes(g.key))
      .map((g) => ({ g, list: all.filter((s) => s.bucket === g.key) }))
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

  row(s, now, showStatus) {
    const g = GROUPS.find((x) => x.key === s.bucket);
    const item = new vscode.TreeItem(s.title || s.id);
    item.id = "session:" + (s.workstreamId || s.id);
    item.sessionId = s.id;
    item.leadId = s.leadId;
    item.workstreamId = s.workstreamId;
    item.leadDone = !!s.completed;
    item.topic = s.topic;
    item.bucket = s.bucket;
    item.autoTopic = s.autoTopic;
    item.topicPinned = s.topicPinned;
    item.contextValue = `session;done=${s.completed ? 1 : 0};cont=${s.choice === "continue" ? 1 : 0}`;
    item.description =
      (showStatus ? g.label + " · " : "") +
      age(now - (s.activity || s.last_ts || now)) +
      (s.codexOnly ? " · Codex" : "") +
      (s.count > 1 ? ` · ${s.count} chats` : s.continued ? " · continued" : "") +
      (s.tickets.length ? " · " + s.tickets[0] + (s.tickets.length > 1 ? ` +${s.tickets.length - 1}` : "") : "");
    item.iconPath = new vscode.ThemeIcon(s.flag ? "star-full" : "circle-filled", new vscode.ThemeColor(g.color));
    const tip = new vscode.MarkdownString();
    tip.appendMarkdown(`**${(s.title || "").replace(/[*_`]/g, "")}**\n\n`);
    if (s.detail) tip.appendText(s.detail + "\n\n");
    if (s.last_text) tip.appendText(s.last_text + "\n\n");
    if (s.tickets.length) tip.appendText("Tickets: " + s.tickets.join(", ") + "\n\n");
    tip.appendText(`${s.project || ""} · ${s.root}`);
    item.tooltip = tip;
    item.command = { command: "agentBoard.open", title: "Open session", arguments: [s.id] };
    return item;
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
      if (this.byTopic()) {
        const rows = this.topicRows();
        return [
          ...this.groups(TOPIC_TOP),
          ...[...this.topics(), null]
            .map((name) => ({ name, list: rows.filter((s) => s.topic === name) }))
            .filter((x) => x.list.length)
            .map(({ name, list }) => {
              const item = new vscode.TreeItem(
                name || "Ungrouped",
                this.filter || (name && list.some((s) => s.bucket !== "idle")) ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed
              );
              item.id = "topic:" + (name === null ? "" : "n:" + name) + (this.filter ? ":f" : "");
              item.description = String(list.length);
              item.contextValue = name ? "topic" : "ungrouped";
              item.topic = name;
              item.iconPath = new vscode.ThemeIcon(name ? "tag" : "inbox");
              return item;
            }),
          ...this.groups(TOPIC_BOTTOM),
        ];
      }
      return this.groups(GROUPS.map((g) => g.key));
    }
    const now = this.data.now;
    // Idle rows fold behind one node, so a topic opens as a short list.
    if (el.contextValue === "topic" || el.contextValue === "ungrouped") {
      const rows = this.topicRows().filter((s) => s.topic === el.topic);
      const idle = rows.filter((s) => s.bucket === "idle");
      const items = rows.filter((s) => s.bucket !== "idle").map((s) => this.row(s, now, true));
      if (idle.length) {
        const item = new vscode.TreeItem("Idle", this.filter ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed);
        item.id = "idle:" + (el.topic === null ? "" : "n:" + el.topic) + (this.filter ? ":f" : "");
        item.description = String(idle.length);
        item.contextValue = "topicIdle";
        item.topic = el.topic;
        items.push(item);
      }
      return items;
    }
    if (el.contextValue === "topicIdle") {
      return this.topicRows()
        .filter((s) => s.topic === el.topic && s.bucket === "idle")
        .map((s) => this.row(s, now, false));
    }
    if (el.contextValue !== "group") return [];
    return this.sessions()
      .filter((s) => s.bucket === el.groupKey)
      .sort((a, b) => (b.activity || 0) - (a.activity || 0))
      .map((s) => this.row(s, now, false));
  }
}

// Count tiles for the statuses worth a look, in their own collapsible view.
const TILES = ["asking", "check", "active", "yourturn", "pending"];

class Overview {
  constructor(provider) {
    this.provider = provider;
    this.view = null;
  }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = overviewHtml();
    // The page asks for counts each time it loads, which includes every re-show.
    view.webview.onDidReceiveMessage((m) => (m.bucket ? vscode.commands.executeCommand("agentBoard.pick", m.bucket) : this.post()));
    view.onDidDispose(() => (this.view = null));
  }

  visible() {
    return !!this.view && this.view.visible;
  }

  // Counts ignore the search filter, so the tiles always show the whole board.
  post() {
    if (!this.view) return;
    const rows = this.provider.sessions(true);
    this.view.webview.postMessage({
      down: !!this.provider.error && !this.provider.data,
      tiles: TILES.map((key) => {
        const g = GROUPS.find((x) => x.key === key);
        return { key, label: g.label, color: g.color.replace(/\./g, "-"), n: rows.filter((s) => s.bucket === key).length };
      }),
    });
  }
}

function overviewHtml() {
  const nonce = crypto.randomBytes(16).toString("hex");
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'">
<style nonce="${nonce}">
  body { padding: 4px 10px 10px; }
  #tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 6px; }
  .tile {
    border: none; border-radius: 7px; padding: 7px 9px; text-align: left; cursor: pointer;
    font: inherit; color: var(--vscode-foreground);
    background: color-mix(in srgb, var(--c) 18%, var(--vscode-sideBar-background));
    box-shadow: inset 3px 0 0 var(--c);
  }
  .tile:hover { background: color-mix(in srgb, var(--c) 32%, var(--vscode-sideBar-background)); }
  .tile:focus-visible { outline: 1px solid var(--vscode-focusBorder); }
  .tile.zero { opacity: .5; cursor: default; }
  .n { display: block; font-size: 18px; font-weight: 600; line-height: 1.15; }
  .l { display: block; font-size: 11px; opacity: .8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #down { margin: 8px 0 0; font-size: 11px; opacity: .8; }
</style>
</head>
<body>
<div id="tiles"></div>
<p id="down" hidden>Agent Board is not reachable</p>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const tiles = document.getElementById("tiles");
  window.addEventListener("message", (e) => {
    document.getElementById("down").hidden = !e.data.down;
    tiles.replaceChildren(...e.data.tiles.map((t) => {
      const b = document.createElement("button");
      b.className = "tile" + (t.n ? "" : " zero");
      b.disabled = !t.n;
      b.style.setProperty("--c", "var(--vscode-" + t.color + ")");
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = t.n;
      const l = document.createElement("span");
      l.className = "l";
      l.textContent = t.label;
      b.append(n, l);
      b.addEventListener("click", () => vscode.postMessage({ bucket: t.key }));
      return b;
    }));
  });
  vscode.postMessage({});
</script>
</body>
</html>`;
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
  async function saveTopic(items, topic) {
    provider.move(items, topic);
    try {
      for (const it of items)
        await request("POST", "/api/topic", it.workstreamId ? { id: it.workstreamId, scope: "workstream", topic } : { id: it.sessionId, scope: "session", topic });
    } catch (e) {
      vscode.window.showErrorMessage("Could not change the group. The board service may need the update with group picking. " + (e.message || e));
    }
    await refresh();
  }

  // Drag rows onto a group, its Idle fold, or any row already in that group.
  // Ungrouped hands a row back to keyword matching.
  const DRAG = "application/vnd.code.tree.agentboard.sessions";
  const dragAndDropController = {
    dragMimeTypes: [DRAG],
    dropMimeTypes: [DRAG],
    handleDrag(source, dataTransfer) {
      const rows = source.filter((it) => it.sessionId);
      if (rows.length) dataTransfer.set(DRAG, new vscode.DataTransferItem(rows));
    },
    async handleDrop(target, dataTransfer) {
      const rows = dataTransfer.get(DRAG)?.value;
      if (!target || !Array.isArray(rows) || !rows.length || !provider.byTopic()) return;
      if (!["topic", "ungrouped", "topicIdle"].includes(target.contextValue) && !(target.sessionId && ![...TOPIC_TOP, ...TOPIC_BOTTOM].includes(target.bucket))) return;
      const topic = target.contextValue === "ungrouped" ? "" : target.topic || "";
      const moving = rows.filter((it) => (it.topic || "") !== topic || (!topic && it.topicPinned));
      if (moving.length) await saveTopic(moving, topic);
    },
  };
  const view = vscode.window.createTreeView("agentBoard.sessions", { treeDataProvider: provider, dragAndDropController, canSelectMany: true });
  context.subscriptions.push(view);
  const overview = new Overview(provider);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("agentBoard.overview", overview),
    provider.onDidChangeTreeData(() => overview.post())
  );

  async function refresh() {
    try {
      const data = JSON.parse(await request("GET", "/api/status"));
      provider.set(data, null);
      stopStaleService(data.version);
      const n = (data.workstreams || data.sessions).filter((s) => ["asking", "check", "yourturn"].includes(s.bucket)).length;
      view.badge = n ? { value: n, tooltip: `${n} need you` } : undefined;
    } catch (e) {
      startBoard();
      provider.set(provider.data, String(e.message || e));
    }
  }

  let timer;
  function schedule() {
    clearInterval(timer);
    timer = setInterval(() => (view.visible || overview.visible()) && refresh(), cfg().refresh * 1000);
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
    // Done acts on the whole workstream; Continue later acts on its lead chat,
    // the same targets the board's own buttons use.
    ...[
      ["agentBoard.markDone", (it) => [it.workstreamId ? ["/api/group-complete", { id: it.workstreamId, on: true }] : ["/api/complete", { id: it.sessionId, on: true }]]],
      ["agentBoard.undoDone", (it) => [
        ...(it.workstreamId ? [["/api/group-complete", { id: it.workstreamId, on: false }]] : []),
        ...(!it.workstreamId || it.leadDone ? [["/api/complete", { id: it.leadId || it.sessionId, on: false }]] : []),
      ]],
      ["agentBoard.continueLater", (it) => [["/api/choice", { id: it.leadId || it.sessionId, choice: "continue" }]]],
      ["agentBoard.clearContinue", (it) => [["/api/choice", { id: it.leadId || it.sessionId, choice: "clear" }]]],
    ].map(([cmd, calls]) =>
      vscode.commands.registerCommand(cmd, async (item) => {
        if (!item || !item.sessionId) return;
        try {
          for (const [urlPath, body] of calls(item)) await request("POST", urlPath, body);
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
          vscode.window.showInformationMessage("Handoff prompt copied. Paste it into the new Codex chat.");
        }
      } catch (e) {
        vscode.window.showErrorMessage(
          "Could not start a handoff session. The board service may need the update with Handoff to new session. " + (e.message || e)
        );
      }
    }),
    // A hand-picked group wins over keyword matching; Auto hands it back.
    vscode.commands.registerCommand("agentBoard.setTopic", async (item) => {
      if (!item || !item.sessionId) return;
      const current = item.topicPinned ? item.topic : "";
      const picks = [
        { label: "Auto", description: item.autoTopic || "No topic", topic: "" },
        ...provider.topics().map((t) => ({ label: t, topic: t })),
        { label: "$(add) New group…", topic: null },
      ].map((p) => ({ ...p, picked: p.topic === current, detail: p.topic === current ? "Current" : undefined }));
      const choice = await vscode.window.showQuickPick(picks, { placeHolder: `Move "${item.label}" to a group` });
      if (!choice) return;
      let topic = choice.topic;
      if (topic === null) {
        topic = ((await vscode.window.showInputBox({ prompt: "New group name", validateInput: (v) => (v.trim().length > 80 ? "80 characters max" : null) })) || "").trim();
        if (!topic) return;
      }
      await saveTopic([item], topic);
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
    vscode.commands.registerCommand("agentBoard.toggleGroupBy", async () => {
      const c = vscode.workspace.getConfiguration("agentBoard");
      const next = c.get("groupBy", "status") === "topic" ? "status" : "topic";
      await c.update("groupBy", next, vscode.ConfigurationTarget.Global);
      if (next === "topic" && !provider.topics().length) {
        vscode.window.showInformationMessage("Agent Board has no topics yet. Add them to agent_board_topics.json in its data folder.");
      }
    }),
    // A tile click lists that status's rows, whichever way the list is grouped.
    vscode.commands.registerCommand("agentBoard.pick", async (bucket) => {
      const g = GROUPS.find((x) => x.key === bucket);
      if (!g || !provider.data) return;
      const now = provider.data.now;
      const picked = await vscode.window.showQuickPick(
        provider
          .sessions(true)
          .filter((s) => s.bucket === bucket)
          .sort((a, b) => (b.activity || 0) - (a.activity || 0))
          .map((s) => ({ label: s.title || s.id, description: age(now - (s.activity || s.last_ts || now)), id: s.id })),
        { placeHolder: g.label }
      );
      if (picked) vscode.commands.executeCommand("agentBoard.open", picked.id);
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
