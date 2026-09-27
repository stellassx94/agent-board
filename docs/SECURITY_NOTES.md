# Security notes for colleague pilots

## Deferred: private key for the local board connection

Agent Board binds its HTTP service to `127.0.0.1`, so it is reachable only from the same Mac. The service currently has no authentication: another local process or another user account on a shared Mac could request board summaries or change board choices. Browser `Host` and `Origin` checks reduce access from ordinary websites, but they do not authenticate local programs.

The pilot assumes a managed Mac used by one person. A random per-install key is deferred for now because it would add setup and failure points across the Mac app, browser view, and optional SwiftBar plugin, with limited additional protection against software already running as that same person. Such software could usually read the underlying Claude and Codex session files directly.

Revisit this before using Agent Board on shared Macs or expanding its local API. Generate the key on first launch, store it in a user-only file, require it on every API request, and keep the existing `Host` and `Origin` checks. Do not put the key in a URL or commit it to Git. Test the Mac window, browser view, SwiftBar plugin, and app restart together.

## App updater trust model

The Mac app checks for updates only when the user selects **Check for updates**. It reads the latest non-draft, non-prerelease version from the public `stellassx94/agent-board` GitHub release API over HTTPS. It shows the version before offering a separate **Download and install** action and requires a final **Install and relaunch** confirmation. It never installs on launch or in the background.

The updater accepts only the expected Apple Silicon ZIP URL for that exact release. It verifies the downloaded byte count and SHA-256 against GitHub's release-asset digest, rejects unexpected archive paths, and checks the extracted app's bundle identifier, app version, bundled service version, and macOS code-signature structure before copying it beside the current app. The old app is retained as a sibling backup; if the swap or relaunch command fails, the helper attempts to restore it. It does not modify `~/.agent-board/`, and it cannot replace an app in a read-only or unwritable location.

This is **not independent publisher authentication**: the asset and its digest come from the same GitHub release account, and the current app is ad-hoc signed, not Developer ID signed or notarized. A compromised release account could replace both the ZIP and digest with a malicious but internally valid app. HTTPS and the digest protect transfer integrity, while the bundle and code-signature checks catch mismatches or damage; they do not establish who published the code. Review the release and follow organizational policy before installing. The updater replaces only the app bundle; optional hooks installed separately must be updated separately.
