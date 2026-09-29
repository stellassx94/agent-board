# Agent Board Sidebar

Compact VS Code sidebar list of Claude Code and Codex sessions, read from the local Agent Board (`http://127.0.0.1:8765/api/status`). Private, local only.

- Click a session to open it.
- The ↻ icon, or right-click **Resume in new chat**, starts a fresh chat in the session's own app with a resume-skill prompt (Agent Board v0.4.13 or later).
- Inline and right-click actions mark a session done or save it for Continue later.

If the board is not running, the extension starts the service inside the installed Agent Board app (`~/Applications` or `/Applications`). Set `agentBoard.scriptPath` to use a different `agent_board.py`.

## Build and install

Run `sh vscode-extension/package.sh` from the repository. It writes `build/agent-board-sidebar-<version>.vsix` without npm. Install it with `code --install-extension build/agent-board-sidebar-<version>.vsix`, then run **Developer: Reload Window**.
