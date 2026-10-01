# Agent Board v0.4.25

This release builds on v0.4.24. It lets a renamed chat name its workstream card.

- **Renamed chats name their card.** A workstream card used to keep the title of its original chat, even after you renamed a resumed chat in it with Claude Code's `/rename`. The card now shows the newest renamed title among its chats. A workstream with no renamed chat still shows its original chat's title.
- All other board behavior is unchanged. The sidebar is 0.4.25, the same version as the app.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.25-macos-arm64.zip` (SHA-256 `67fb6c45282f941a7c2421217b9167fdf66c81014351419962f8ea3cc6231bea`). The VS Code extension is `agent-board-sidebar-0.4.25.vsix` (SHA-256 `b1af7d4f709466aca47632eb34e2e20a4635eeab1cc610c0e3628127d12d662c`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
