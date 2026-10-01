# Agent Board v0.4.24

This release builds on v0.4.23. It lets you choose a row's topic group by hand.

- **Drag rows into a group.** In the VS Code sidebar's topic view, drag one or more rows (Cmd or Shift to pick several) onto a topic, its Idle fold, or any row already in that topic. Dropping on **Ungrouped** returns the rows to keyword matching. The row moves at once and the board service confirms it on the next refresh.
- **Move to group…** The sidebar's tag icon, or right-click **Move to group…**, picks a group from a list. **New group…** adds a group that is not in the topics file, and **Auto** returns the row to keyword matching. The board's detail pane has the same choice under **Group**.
- **Hand-picked groups win.** A picked group beats keyword matching, and a workstream's pick covers its linked chats. Picks are saved in `agent_board_topic_choices.json` in the personal data directory.
- All other board behavior is unchanged. The sidebar is 0.4.24, the same version as the app. Group picking needs both the v0.4.24 app and the 0.4.24 sidebar.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.24-macos-arm64.zip` (SHA-256 `1b8f86a6a62fe95d240a6c6b73b02c536ceb75ea7b028f51b87586410917e314`). The VS Code extension is `agent-board-sidebar-0.4.24.vsix` (SHA-256 `8cb04dc3f2dce703195b3d7f03f4b61e5fbe69a2720befd17c304e9187825683`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
