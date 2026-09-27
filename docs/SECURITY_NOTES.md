# Security notes for colleague pilots

## Deferred: private key for the local board connection

Agent Board binds its HTTP service to `127.0.0.1`, so it is reachable only from the same Mac. The service currently has no authentication: another local process or another user account on a shared Mac could request board summaries or change board choices. Browser `Host` and `Origin` checks reduce access from ordinary websites, but they do not authenticate local programs.

The pilot assumes a managed Mac used by one person. A random per-install key is deferred for now because it would add setup and failure points across the Mac app, browser view, and optional SwiftBar plugin, with limited additional protection against software already running as that same person. Such software could usually read the underlying Claude and Codex session files directly.

Revisit this before using Agent Board on shared Macs or expanding its local API. Generate the key on first launch, store it in a user-only file, require it on every API request, and keep the existing `Host` and `Origin` checks. Do not put the key in a URL or commit it to Git. Test the Mac window, browser view, SwiftBar plugin, and app restart together.
