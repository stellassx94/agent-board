# Agent Board Sidebar

Compact VS Code sidebar list of Claude Code and Codex sessions, read from the local Agent Board (`http://127.0.0.1:8765/api/status`). Private, local only.

- Each row is one workstream, the same as the board's Workstreams view, so a resumed chat joins its original row and the counts match the app. A row with linked chats shows `N chats`.
- Click a row to open its latest chat.
- The handoff icon, or right-click **Handoff to new session**, starts a fresh chat in the session's own app with a resume-skill prompt (Agent Board v0.4.13 or later).
- Inline and right-click actions mark a workstream done or save it for Continue later.
- The list-tree icon switches between grouping by status and grouping by topic. Topics come from the board service (`agent_board_topics.json` in the Agent Board data folder), so the app and the sidebar agree. The topic view keeps Asking you, Check me, Working and Your turn at the top, files the other live rows under their topic with idle rows folded into one **Idle** node, and leaves Temporary and Completed at the bottom. In topic view, drag rows (several at once with Cmd or Shift) onto a topic, its Idle fold, or a row already in it to move them there; drop on **Ungrouped** to return them to keyword matching. The tag icon, or right-click **Move to group…**, does the same from a list and can add a new group (Agent Board v0.4.24 or later).
- Rows show the ticket keys they mention, such as `ABC-1234`, and search matches them. `agentBoard.ticketPrefixes` limits which prefixes count.
- The collapsible **Overview** section shows count tiles for Asking you, Check me, Working, Your turn and Continue later. Click a tile to pick a session in that status.

If the board is not running, the extension starts the service inside the installed Agent Board app (`~/Applications` or `/Applications`). Set `agentBoard.scriptPath` to use a different `agent_board.py`.

## Build and install

The sidebar carries the same version as the Agent Board app, and the release check refuses a mismatch. Run `sh vscode-extension/package.sh` from the repository. It writes `build/agent-board-sidebar-<version>.vsix` without npm. Install it with `code --install-extension build/agent-board-sidebar-<version>.vsix`, then run **Developer: Reload Window**.
