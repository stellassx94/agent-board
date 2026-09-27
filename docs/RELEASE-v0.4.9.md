# Agent Board v0.4.9

This release builds on v0.4.8 and adds a manual Mac app updater. Existing v0.4.8 users must install v0.4.9 manually once; subsequent app updates can use the menu.

- **Check for updates** reads the latest public GitHub release when selected and shows its version before any download.
- **Download and install** verifies the expected Apple Silicon ZIP's size and GitHub-reported SHA-256, checks the extracted app bundle and signature, and stages it beside the current app.
- A separate **Install and relaunch** confirmation quits the app, keeps a rollback copy, replaces the app bundle, and restarts its service.
- The updater does not check on launch, install silently, change `~/.agent-board/` settings, or update separately installed optional hooks.

The ZIP and its digest come from the same GitHub account; the current app is ad-hoc signed, not notarized. These checks protect transfer integrity but do not independently authenticate the publisher. See [the updater trust model](SECURITY_NOTES.md).

Download **Agent Board v0.4.9 for Apple Silicon (.zip)** and verify SHA-256 `ebb29b59c104e20e7b7adf2264bba7bdec4dbd93c24caad8a8222c5fc3b88fda`. The extracted app and bundled service both report v0.4.9. The app targets macOS 13 or later, is ad-hoc signed and not notarized, and may require **Open Anyway**. Update any separately installed optional Stop hook from this version's source as well.

The private GitLab release may provide the same app as a `.tar.xz` if its ZIP upload limit rejects the ZIP. That archive's SHA-256 is `7746db2ce33ac3a2cd5ebd38427ff92c389bb8b2c2f7a52b4f66f5bb63af648a`.
