# Agent Board v0.4.8

A short **continue later** chat closeout now moves to Continue Later on the board's first refresh after the user message appears. It no longer passes through Running and Your turn while waiting for the Stop hook.

- The board detects the explicit closeout from a recent user message and saves the completion marker and star immediately. The Stop hook remains a backup.
- Assistant activity after that message keeps the session parked. A later substantive user message reopens it.
- Undo and removing the star stay authoritative if a Stop hook arrives late. Questions and longer requests do not trigger automatic parking.
- The web board checks for updates every two seconds and skips overlapping requests.

## Installation

Download **Agent Board v0.4.8 for Apple Silicon (.zip)** from this release, unzip it, and open `Agent Board.app`. ZIP SHA-256: `419f0bdb4415c2c82e1a0bf2dd14aa71512c647532834cf7db5ed3d27277804b`. The app targets macOS 13 or later, is locally signed and not notarized, and updates manually. If you use the optional Stop hook, update its installed source alongside the app.

The private GitLab release may carry the same app as a `.tar.xz` archive if its ZIP endpoint rejects the larger file. Tar SHA-256: `1ea491fceb3f5c743b1aa569aeb3ccc861c1684696235f1cdec334877b0a6a20`.
