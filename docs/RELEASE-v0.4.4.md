# Agent Board v0.4.4

Newly finished sessions stay in **Needs your attention → Your turn** before any automatic suggestion can move them elsewhere. Suggestions remain visible on the card; your explicit Done, Continue later, and Temporary choices still control its placement.

The Temporary suggestion now applies only to short questions that end with a question mark. A request such as “do some research…” no longer counts as a one-off question.

Verified against the reported Codex session in the live v0.4.4 Mac app. The app targets Apple Silicon and macOS 13 or later. It is locally signed and not notarized; updates remain a manual download and install.

## Installation choices

- Download **Agent Board v0.4.4 for Apple Silicon (.zip)** from this release, unzip it, and open `Agent Board.app`. The published ZIP has SHA-256 `425a2a70bff33d448e61dd09ae3906863502aecc99854ff4698f95e36096e2be`.
- Or clone the private repository and run `sh macos/build.sh` to build the app on your own Mac. This requires Xcode Command Line Tools, `uvx`, and package-index access.

Both choices run the board locally and keep personal settings under `~/.agent-board/`. The ready-built app is not Apple-notarized, so macOS may require an explicit **Open Anyway** decision in System Settings → Privacy & Security. See [the colleague quickstart](colleague-intro/QUICKSTART.md) for the full steps.
