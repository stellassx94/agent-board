# Agent Board v0.4.17

This release builds on v0.4.16. It gives chats started with **Resume in new chat ↻** a readable name.

- **Resume chats are named after the session they continue.** Claude names a new chat from its first message. Before, that message started with "Use the resume skill to pick up session …", so the new chat was named something like "Resume session 7e67c9d3". The prompt now starts with `Continue:` and the source session's title, shortened to 40 characters, for example `Continue: Agent board release — use the resume skill to pick up session …`. When the source title is itself a generic resume title, the prompt keeps the old wording.
- **The board recognises the new prompt.** A chat whose title is the new prompt shows the source session's title with the `· continued` tag. If the source session is no longer on the board, the chat shows the title from its prompt.
- Regression tests cover the new prompt and both title cases. All other board behavior is unchanged.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.17-macos-arm64.zip` (SHA-256 `73c73f2df7431059e597169a48a412e0f5534285bf6b0b3996f803fa9e776a60`). The VS Code extension is unchanged; keep `agent-board-sidebar-0.3.2.vsix` from v0.4.16. The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The digests and packages come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app; use **Check for updates…** in v0.4.9 or later.
