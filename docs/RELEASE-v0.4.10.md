# Agent Board v0.4.10

This release builds on v0.4.9 and improves Codex approval visibility.

- An unresolved escalated Codex command appears under **Needs your attention / Asking you** after ten seconds, with "may be awaiting approval" wording. The board infers this from the pending tool call; it cannot inspect the Codex approval dialog directly.
- Tool output, a new user message, or turn completion clears the inferred approval state. Ordinary commands and mere mentions of escalation do not trigger it.
- The v0.4.9 manual updater and all existing board controls remain unchanged. Nothing installs automatically; your current Mac app is not changed by publishing this release.

The Apple Silicon macOS ZIP is `Agent-Board-v0.4.10-macos-arm64.zip` (SHA-256 `d310f1e5f9af079f86ca9cd402da072b808ccee4072b176b3cdec85d41d0da04`). The GitLab release may offer a `.tar.xz` fallback (SHA-256 `c51c918c12247a49e215e0d93664a7850d57c8a9456fe200ba0c206efff348d0`). Both extracted apps were signed and verified locally. The app targets Apple Silicon macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. Existing v0.4.8 app users still need to install v0.4.9 or later manually once to use the updater.
