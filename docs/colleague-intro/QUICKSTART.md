# Agent Board — colleague pilot

Agent Board puts your local Claude Code and Codex sessions into a Mac menu bar and workstream board. It reads the session history on **your own Mac**. Your stars, choices, and workstream links are stored locally under `~/.agent-board/`.

## Choose how to install

Both options need macOS 13 or later. The [Agent Board GitHub project](https://github.com/stellassx94/agent-board) and its release downloads are public, so no repository invitation or corporate VPN is required. The ready-built app is for Apple Silicon Macs; Intel has not been tested.

### Option A — download the ready-built app

1. Open the [v0.4.8 release](https://github.com/stellassx94/agent-board/releases/tag/v0.4.8) and download **Agent Board v0.4.8 for Apple Silicon (.zip)**.
2. Unzip it and put `Agent Board.app` in the location where you plan to keep it. It needs neither Xcode Command Line Tools nor `uvx`.
3. Open **System Settings → Privacy & Security → Accessibility**. Add `Agent Board.app` with the **+** button if it is not listed and switch it on. This permission is required. Then open Agent Board; if it is already running, quit and reopen it. If you move or replace the app later, macOS may ask you to grant access again.
4. Accessibility access and Gatekeeper approval are separate. If macOS blocks this locally signed, non-notarized app, verify that it came from the official GitHub release, then use **System Settings → Privacy & Security → Open Anyway** if your Mac permits it. Do not change either setting if your company policy blocks it.

The downloaded ZIP's SHA-256 is `b10a0cf8eb4ce60c88786b499d6c3e87e8acdad7119991970aa738de54304f6e`. The same source-build option remains below.

### Option B — build from source

You need Xcode Command Line Tools and `uvx` in Terminal. If you use Homebrew, `brew install uv` provides `uvx`. `xcode-select --install` installs the Apple command line tools. The build downloads pinned Python and PyInstaller versions, so it also needs package-index access.

```bash
git clone https://github.com/stellassx94/agent-board.git
cd agent-board
sh macos/build.sh
open "build/Agent Board.app"
```

The build bundles the Python service and runtime. A colleague running the built app does not need to install Python or SwiftBar. The build is for the Mac architecture used to create it. The pilot app is locally signed and has not been notarized.

Before first use, open **System Settings → Privacy & Security → Accessibility**, add `build/Agent Board.app` with the **+** button if needed, and switch it on. Then open Agent Board; if it is already running, quit and reopen it. If you later copy the app to Applications, grant Accessibility access to that final copy.

If you want the app in your personal Applications folder after trying it:

```bash
mkdir -p "$HOME/Applications"
ditto "build/Agent Board.app" "$HOME/Applications/Agent Board.app"
open "$HOME/Applications/Agent Board.app"
```

## Try four things

1. Find a recent session in **Working**, **Your turn**, or **Check me**.
2. Star a follow-up for **Continue later**.
3. Link a resumed session to its earlier workstream.
4. Mark a finished workstream **Done** yourself. Suggestions are advisory.

The menu bar item opens the board and shows workstream counts. Closing the board window leaves the menu bar item running. The app starts its local service when needed. You can use **Launch at Login** in the app menu.

## Check your version and update

The menu shows the installed app version and the running board service version. A warning symbol means they differ, usually because an older service is already using the local port. **View releases…** opens the public GitHub release page in your browser so you can compare versions and download the latest app. The pilot app does not install updates automatically.

To update a downloaded app, choose **Quit Agent Board**, download the next release ZIP, and replace the old app while it is closed. To update a source-built app, quit, then run `git pull --ff-only` and `sh macos/build.sh` in your checkout. If you copied the previous app into Applications, replace that copy while it is closed. Your board choices remain in `~/.agent-board/`.

## If something looks wrong

- Empty board: check that Claude Code or Codex has session history on this Mac; the app cannot show someone else's sessions.
- Cannot download or clone: confirm that `github.com` is reachable from your network. The HTTPS clone command above does not require SSH setup.
- Build fails: check `xcode-select -p` and `uvx --version`; share the error output with the pilot owner.
- Board fails to load: use **Retry service** in the app menu, then share `~/.agent-board/app-service.log` only after checking it for sensitive local paths or session details.

**Feedback:** Tell the pilot owner what was hard to install, which session was missing, or which status looked wrong. Do not send session logs or screenshots containing private work without reviewing them first.

Source: Agent Board source, README, and macOS build script reviewed 27 Sep 2026. A clean-Mac colleague install has not yet been validated.
