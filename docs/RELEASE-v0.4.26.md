# Agent Board v0.4.26

This release builds on v0.4.25. It stops the board service from choking when many windows ask for updates at once.

- **One build at a time.** Each refresh used to rebuild the whole board from your session files. With several VS Code windows open, requests piled up and the service ran at about 100% CPU. Now one build runs at a time, and waiting requests share its answer.
- **Short-lived saved answer.** The service keeps each board answer for 3 seconds. A button press (flag, done, link or topic) clears it, so your change shows on the next refresh.
- **Quieter log.** A client that stops waiting no longer writes a "Broken pipe" error to the log.
- All other board behavior is unchanged. The sidebar is 0.4.26, the same version as the app.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.26-macos-arm64.zip` (SHA-256 `93af724a78f0101d03ae73091b85c00e574e01667e2f17b615665592c8e3fd29`). The VS Code extension is `agent-board-sidebar-0.4.26.vsix` (SHA-256 `064436659b6998acef40032e358c95a8d049ae862a9489af779cab8eec2da090`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
