# Agent Board v0.4.13

This release builds on v0.4.12 and adds one board action.

- **Resume in new chat ↻.** Each workstream and linked session now has a button that starts a fresh chat instead of reopening the old one. The chat opens in the same app as the original session: the Claude app, Claude Code in VS Code, the Codex app, or Terminal for command-line sessions. It is pre-filled with a prompt that asks the resume skill to read that session's shared `~/.agent-handoffs/` snapshot, so the new chat re-orients cheaply without replaying the old transcript. In VS Code, the session's folder window is focused first, as **Open ↗** does since v0.4.12.
- The Codex VS Code extension has no link that fills a new chat. For those sessions the prompt is copied to the clipboard and Codex is brought forward; paste it into a new chat.
- Most apps pre-fill the prompt and wait for you to press Enter.
- The service exposes the action at `POST /api/resume-new?id=<session>`, so other clients, such as a sidebar extension, can use the same behavior.
- Regression tests cover the app choice and the link for each app. All other board behavior is unchanged.
