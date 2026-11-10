# Move Agent Board to another Mac

This guide is for a person or a local coding agent. Read `AGENTS.md` first.
The Git repositories contain application source, examples and build instructions.
They do **not** contain personal board state, agent session history, credentials,
macOS permissions or a complete backup of a working installation.

## 1. Preserve the old installation privately

Save work and quit Agent Board before the final copy. Keep the old Mac or a
verified backup available until the new installation passes acceptance.

Transfer the following through an approved private migration/backup process:

- The current `Agent Board.app` from its installed location, if keeping that
  build. A displayed version alone does not establish source equality.
- The entire `~/.agent-board/` directory, including configuration, choices,
  completion markers, lineage, flags, topics, topic choices and custom CSS.
  If `AGENT_BOARD_DATA_DIR` or `AGENT_BOARD_CONFIG` is set, locate and transfer
  those actual locations instead. Never replace a populated destination
  silently; back it up and reconcile changes first.
- The actual Claude project/session directories referenced by `claude_roots`
  and the Codex directory referenced by `codex_dir`. Defaults are
  `~/.claude/projects` and `~/.codex` (including sessions and session index).
  Preserve session IDs and historical paths. An empty history directory can
  produce an empty board even when board preferences were transferred.
- `~/.agent-handoffs/` if using handoff to a new session, and relevant Claude
  settings/hooks. Copy complete agent databases consistently with apps closed;
  do not copy only a SQLite main file while discarding active WAL data.
- Local source changes separately from Git remotes. A fresh clone cannot
  restore uncommitted or untracked work from another checkout.

Do not commit these private files, exported status, transcripts or credentials
to either repository. A migration report or checker is not the data backup.

## 2. Obtain source or use the transferred app

Source is available from either remote:

```sh
git clone https://github.com/stellassx94/agent-board.git
cd agent-board
git log -1 --oneline
```

The corporate alternative is `gitlab@git.garena.com:stella.simsx/agent-board.git`.
Read the current main branch and relevant release notes before selecting a
build. A release artifact can predate changes on main even when `VERSION`
has not changed. Do not replace a known working transferred app with an older
download merely because the visible version matches.

For a native app built from source, use `sh macos/build.sh`. It requires Xcode
Command Line Tools and `uvx`; the build downloads its pinned Python/PyInstaller
runtime. Verify `codesign --verify --deep --strict "build/Agent Board.app"`.
Keep a recoverable copy of any destination app before replacing it while closed.
For a browser-only fallback, `python3 agent_board.py --no-open` starts the local
service. Do not run it alongside an existing native service on the same port.

## 3. Restore dependencies and permissions

Keep the same home username when practical. Otherwise review configuration,
hook commands, source directories and old project paths for broken references;
do not bulk rewrite historical session IDs or transcripts.

Put the native app in its final location, open it, and grant required
Accessibility access in System Settings. Permission grants may need renewal
after migration or app replacement. Follow company restrictions; do not bypass
security controls. Configure Launch at Login only after validating the app.

Check that old LaunchAgents or SwiftBar plugins do not start a second service.
If a legacy launcher was disabled on the old Mac, preserve that intent; copied
plist files do not guarantee copied launchctl disabled overrides.

Review Claude hook commands against the new app's installed path. The optional
setup in the app can add hooks after explicit confirmation and makes a backup
of Claude settings first. Merging hooks must preserve unrelated settings.

## 4. Acceptance for the new Mac and its agent

- Verify the app bundle/source and expected features, not only `VERSION`.
- Confirm one listener at the intended localhost port (default 8765), a healthy
  running service, and no duplicate app/service launcher.
- Confirm the board reads the transferred Claude and Codex sources, shows
  known historical sessions and retains completion flags, topics and links.
  Counts can change with activity; compare known examples and state files.
- Open a known session in its correct app/project. Verify resume/handoff paths
  without starting unwanted work or sending prompts automatically.
- Confirm bulk selection UI is present. Do not mass-complete real tasks as a test.
- Confirm finished replies leave Your turn after one hour while explicit
  requests for input remain Asking you. Test with isolated fixtures if needed,
  not by rewriting the user's live history or waiting an hour unnecessarily.
- After hook review, verify status using an ordinary user-authorized task.
  Missing permission-prompt hooks can make Claude approvals appear Working.
- Observe responsiveness under normal use after initial sync/indexing settles.
  Completing a board card does not terminate an underlying agent process.

Report each item as **verified**, **needs user/IT action**, or **not tested**.
Do not call a working clone a completed personal-data restoration. Do not erase
the old Mac or enable duplicate scheduled writers to resolve an uncertain test.
