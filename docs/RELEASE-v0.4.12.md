# Agent Board v0.4.12

This release builds on v0.4.11 and fixes two workstream-board issues.

- **Open ↗ in VS Code opens the right chat.** On macOS, the board now brings forward or opens the VS Code window for the session's folder, then sends the session link. Before, the link went to whichever VS Code window was in front, and the Claude Code extension opened a new blank chat when that window was on another folder. Both steps use macOS Launch Services, so no extra VS Code helper window appears. A separate VS Code profile set in `vscode_user_data_dirs` still uses the `code` command in the same two steps.
- **A fresh reply is no longer hidden by an inherited star.** When a starred workstream is continued in a new linked session, that session's finished reply now shows under **Your turn**. The workstream returns to **Continue later** once the session is idle. A session starred directly still stays in Continue later.
- Regression tests cover both changes. All other board behavior and the v0.4.11 in-app update check are unchanged.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.12-macos-arm64.zip` (SHA-256 `a7bc62b137edf17e91fdee1a24aeb4c2e8d074e95ae31d185d0e7507e4c44e54`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The ZIP digest and package come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
