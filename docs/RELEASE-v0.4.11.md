# Agent Board v0.4.11

This release builds on v0.4.10 and makes the update check available from the board window.

- **Check for updates...** in the Mac app window invokes the same native check as the menu-bar item. It shows the installed app, running service, and latest published release before offering a download.
- A board opened in a regular browser retains the **Releases** link; it cannot invoke the native installer.
- Downloads still require **Download and install** and then **Install and relaunch** confirmation. The app does not check or install automatically.
- The v0.4.10 Codex approval-attention change and all existing board controls remain included.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.11-macos-arm64.zip` (SHA-256 `ef946cf25c9b33e4e05850e52696afc57fc6848b7b7e8511c3b2ae109583148d`). The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. The ZIP digest and package come from the same release account, not independent publisher authentication; see [Security notes](SECURITY_NOTES.md). Publishing does not update an already-running local app.
