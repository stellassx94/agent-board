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
