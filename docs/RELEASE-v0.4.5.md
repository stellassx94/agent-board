# Agent Board v0.4.5

Session activity now follows meaningful conversation events instead of raw transcript file writes.

- Background-task notifications and local-command control records no longer reopen a finished session as **Working**.
- Reconnect, bridge, and cost metadata no longer refresh a session's activity time.
- API limit and other terminal assistant errors are treated as finished turns instead of indefinite generation.
- Genuine user turns, tool results, active tool calls, questions, and background jobs keep their existing live states.

Regression tests cover real user turns, active tools, tool results, task notifications, metadata-only writes, API-limit endings, and background-job completion notifications.

## Installation

- Download **Agent Board v0.4.5 for Apple Silicon (.zip)** from the public GitHub release, unzip it, and open `Agent Board.app`.
- Verify SHA-256: `1fbcb13148e172f4e4a12596eb06e5d275711385839105b2ed68e38bd0bd1566`.
- No corporate VPN, Python, SwiftBar, Xcode Command Line Tools, or `uvx` is required for the ready-built app.
- The app targets Apple Silicon and macOS 13 or later. It is locally signed and not Apple-notarized, so macOS may require **Open Anyway** in System Settings → Privacy & Security.
- Updates remain a manual download and install; the app does not silently replace itself.
