# Agent Board v0.4.7

Saying **continue later** as a short chat closeout now marks the session done and stars its workstream for the **Continue later** list.

- The Stop hook recognizes a short, explicit `continue later` closeout. Questions and longer requests do not trigger it.
- The completion marker remains timestamp-bound: later substantive activity reopens the session. The star persists so the workstream stays easy to find after a linked resume.
- The board shows the session as done while keeping the starred workstream in Continue later. Removing the star moves the finished session to Completed.
- If a Stop hook is missed, the board's bounded fallback can recover this closeout. Existing manual Done, Continue later, Temporary, and star controls remain available.

Regression tests cover phrase recognition, Stop-hook persistence, workstream placement, removal of the star, and later activity. The Mac app and hook source must both be updated to get the new behavior.

## Installation

- Download **Agent Board v0.4.7 for Apple Silicon** from the release page, unzip it, and open `Agent Board.app`.
- Verify SHA-256: `dc96e482ac6e2b2576341ba5506de454a798998b71ac26abdee9cb9c271f381b`.
- The ready-built app requires neither Python, SwiftBar, Xcode Command Line Tools, nor `uvx`.
- The app targets Apple Silicon and macOS 13 or later. It is locally signed and not Apple-notarized; follow the install and Accessibility steps in the README.
- Updates remain manual. If you use the optional Stop hook, update its installed source alongside the app.
