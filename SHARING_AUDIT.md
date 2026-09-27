# Agent Board v0.4.5 public release audit

| Check | Result |
| --- | --- |
| Source | Public release source is based on the reviewed v0.4.5 tree; distribution links were changed from internal GitLab to public GitHub. |
| Personal data | Tracked source contains no personal workspace paths or credentials. Settings, choices, suggestions, links, and logs remain under each user's data directory. The app and ZIP contain no personal board state. |
| Dependencies | The signed app bundles Python 3.13.13 and the backend using PyInstaller 6.22.3. Users need neither Python nor SwiftBar. |
| Session states | Regression tests cover genuine activity, active tools, metadata-only writes, API-limit endings, and background-task notifications. |
| Clean profile | The bundled backend reported v0.4.5 with zero sessions and zero workstreams. |
| Package | The app and extracted ZIP passed `codesign --verify --deep --strict`. ZIP SHA-256: `1fbcb13148e172f4e4a12596eb06e5d275711385839105b2ed68e38bd0bd1566`. |
| Distribution limits | This is an Apple Silicon build for macOS 13 or later. It is locally signed and not notarized. Intel and a second Mac have not been tested. |

The public GitHub release page provides the ready-built download without corporate VPN. Agent Board does not install updates automatically.
