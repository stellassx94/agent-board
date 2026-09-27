# Agent Board v0.4.6 dual-release audit

| Check | Result |
| --- | --- |
| Source | Release source is based on published v0.4.5 plus the reviewed explicit chat-closeout change and shared dual-remote release contract. |
| Personal data | Tracked source contains no personal workspace paths or credentials. Settings, choices, suggestions, links, and logs remain under each user's data directory. The app and ZIP contain no personal board state. |
| Dependencies | The signed app bundles Python 3.13.13 and the backend using PyInstaller 6.22.3. Users need neither Python nor SwiftBar. |
| Session states | Regression tests cover genuine activity, explicit closeout acceptance/rejection, fallback promotion, active tools, metadata-only writes, API-limit endings, and background-task notifications. |
| Clean profile | The bundled backend reported v0.4.6 with zero sessions and zero workstreams. |
| Package | The app and extracted ZIP passed `codesign --verify --deep --strict`. ZIP SHA-256: `b10a0cf8eb4ce60c88786b499d6c3e87e8acdad7119991970aa738de54304f6e`. |
| Distribution limits | This is an Apple Silicon build for macOS 13 or later. It is locally signed and not notarized. Intel and a second Mac have not been tested. |

The public GitHub and private GitLab release pages provide the same reviewed source tag and package bytes. Agent Board does not install updates automatically.

## v0.4.7 Continue later release check

The release delta adds explicit chat parking to the existing v0.4.6 closeout flow. Personal board state stays in each user's data directory; the release source and app contain no session logs, private notes, or credentials. All 16 regression tests, Python and inline JavaScript syntax, bundled-source equality, clean-profile status (zero sessions and workstreams), ZIP extraction, and app signature passed. Local Apple Silicon ZIP SHA-256: `dc96e482ac6e2b2576341ba5506de454a798998b71ac26abdee9cb9c271f381b`. Dual-remote and independent download checks must pass before calling this release complete.

## v0.4.8 faster closeout check

The release delta contains the early explicit closeout, stable completion across assistant activity, an Undo guard, and a two-second non-overlapping board refresh. All 17 regression tests, Python and inline JavaScript syntax, clean-profile bundled status (zero sessions and workstreams), bundled-source equality, ZIP extraction, and app signature passed. The Python backend was rebuilt; the unchanged v0.4.7 Swift native binary was retained and the completed app was re-signed. ZIP SHA-256: `419f0bdb4415c2c82e1a0bf2dd14aa71512c647532834cf7db5ed3d27277804b`. Tar SHA-256: `1ea491fceb3f5c743b1aa569aeb3ccc861c1684696235f1cdec334877b0a6a20`. Remote release and independent download checks remain required.

## v0.4.9 updater release check

Source is based on the published v0.4.8 tag; the delta is limited to the Mac updater, version, trust-model guidance, and release/colleague documentation. No personal configuration, session state, or credentials are included. All 17 regression tests, Python and inline JavaScript syntax, clean-profile bundled status (v0.4.9, zero sessions and workstreams), bundled-source equality, ZIP extraction, and app signature passed. An isolated lower-version test app verified the v0.4.8 GitHub download, staged and swapped it, relaunched, and served v0.4.8 on its isolated port. One candidate smoke launch exited early without a crash report; a diagnostic relaunch served v0.4.9 and checked for updates successfully. Apple Silicon ZIP SHA-256: `ebb29b59c104e20e7b7adf2264bba7bdec4dbd93c24caad8a8222c5fc3b88fda`. A 10 MB tar.xz fallback extracted and verified with SHA-256 `7746db2ce33ac3a2cd5ebd38427ff92c389bb8b2c2f7a52b4f66f5bb63af648a`. GitHub and GitLab release/read-back checks remain required before calling distribution complete.

## v0.4.10 Codex approval attention release check

The release is based on the published v0.4.9 tag and changes only Codex approval-state inference, its regression tests, version, and release/download documentation. An unresolved escalated Codex command enters Asking you after ten seconds with "may be awaiting approval" wording; the signal clears on tool output, a new user message, or turn completion. This is an inference from the log, not direct access to the Codex approval dialog, so a long-running escalated command can briefly appear there. All 20 regression tests, Python and inline JavaScript syntax, clean-profile bundled status (v0.4.10, zero sessions and workstreams), bundled-source equality, ZIP and tar.xz extraction, and app signatures passed. The locally built Apple Silicon ZIP SHA-256 is `d310f1e5f9af079f86ca9cd402da072b808ccee4072b176b3cdec85d41d0da04`; tar.xz SHA-256 is `c51c918c12247a49e215e0d93664a7850d57c8a9456fe200ba0c206efff348d0`. No personal board data is packaged. Remote release and independent download checks are required before distribution is complete.
