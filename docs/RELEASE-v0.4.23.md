# Agent Board v0.4.23

This release builds on v0.4.22. It closes finished script sessions on their own and renames the resume action.

- **Script sessions close themselves.** A session started by a script (`claude -p` or `codex exec`) cannot take a reply. It now moves to Completed five minutes after a clean finish, so it no longer waits in Your turn. A scripted Claude session that ended with an API error stays in Your turn. **Undo done** keeps a scripted session out of Completed.
- **Handoff to new session.** The **Resume in new chat ↻** action is now **Handoff to new session** on the board. The linked-session button is **Handoff**. The sidebar uses an export icon for it instead of the arrow. The action itself is unchanged.
- All other board behavior is unchanged. The sidebar is 0.4.23, the same version as the app.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.23-macos-arm64.zip` (SHA-256 `a1e4e62df87d924d3619c2bfb44dc1bc3d751e755c6b7c03ff2f4a423c08f053`). The VS Code extension is `agent-board-sidebar-0.4.23.vsix` (SHA-256 `7696c150f6ab7a74593958e75bd09d871cce9801739449cd6d6bbf1d36f9af17`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
