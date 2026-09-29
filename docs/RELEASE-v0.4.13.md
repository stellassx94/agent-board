# Agent Board v0.4.13

This release builds on v0.4.12 and adds one board action.

- **Resume in new chat ↻.** Each workstream and linked session now has a button that starts a fresh chat instead of reopening the old one. The chat opens in the same app as the original session: the Claude app, Claude Code in VS Code, the Codex app, or Terminal for command-line sessions. It is pre-filled with a prompt that asks the resume skill to read that session's shared `~/.agent-handoffs/` snapshot, so the new chat re-orients cheaply without replaying the old transcript. In VS Code, the session's folder window is focused first, as **Open ↗** does since v0.4.12.
- The Codex VS Code extension has no link that fills a new chat. For those sessions the prompt is copied to the clipboard and Codex is brought forward; paste it into a new chat.
- Most apps pre-fill the prompt and wait for you to press Enter.
- The service exposes the action at `POST /api/resume-new?id=<session>`, so other clients, such as a sidebar extension, can use the same behavior.
- **VS Code sidebar extension source is now in the repository.** `vscode-extension/` holds Agent Board Sidebar v0.3.0, which adds a ↻ icon and a right-click **Resume in new chat** on each session using the same service action. When the board is not running, it now starts the service inside the installed Agent Board app instead of a standalone `~/.claude/scripts/agent_board.py` copy, which could be stale. Build it with `sh vscode-extension/package.sh`; the release also attaches the `.vsix`.
- Regression tests cover the app choice and the link for each app. All other board behavior is unchanged.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.13-macos-arm64.zip` (SHA-256 `96b7599ebd85273736367493baf9ebbfc853c3c2249d549f8670921318982e59`). The VS Code extension is `agent-board-sidebar-0.3.0.vsix` (SHA-256 `ac76f11712a6e9c9e545e9672fdaec41e7cb0008264c9b7b7c056c1a9641b13e`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
