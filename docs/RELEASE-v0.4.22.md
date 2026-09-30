# Agent Board v0.4.22

This release builds on v0.4.21. It replaces the board's topic menu with a topic view, so topics group the work instead of only filtering it.

- **By status or By topic.** When you have topics, a switch beside Workstreams and Sessions chooses the grouping. **By status** is the board as before. **By topic** keeps Needs your attention and Working at the top, unchanged, and replaces the Continue later, Suggestions and Idle lists with one section per topic. Completed and Temporary stay in Other work. The v0.4.21 topic menu is removed.
- **Topic sections stay short.** Each topic section starts closed and shows its count, the number of rows to pick up, and the number of idle rows. An open section lists the Continue later and suggested rows first. Its idle rows stay behind **Show idle**. Search opens every topic and shows its idle matches.
- **The sidebar folds idle rows the same way.** In the topic view, each topic lists its rows to pick up and keeps its idle rows in one closed **Idle** node. A topic with only idle rows starts closed.
- All other board behavior is unchanged. The sidebar is 0.4.22, the same version as the app.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.22-macos-arm64.zip` (SHA-256 `7603a60215e9a9528c8ee55b859faf8cf76126ca6053764b806847aab94a6195`). The VS Code extension is `agent-board-sidebar-0.4.22.vsix` (SHA-256 `0ffe55004c9b6749d990e28eb994478e1ca525c1cfe0c1648ae312fb0c81442e`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
