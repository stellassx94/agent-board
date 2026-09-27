# Agent Board release contract

When the user says **release Agent Board**, **release this**, or **release `<version>`** while working in this repository, that is explicit authorization to complete the full release workflow below unless the user narrows the destination.

## Required destinations

A release is incomplete until the same reviewed tagged release commit and annotated version tag are published to both remotes:

- GitLab: `gitlab@git.garena.com:stella.simsx/agent-board.git`
- GitHub: `git@github.com:stellassx94/agent-board.git`

Publish matching release pages and downloadable macOS artifacts to both services. Never report the release as complete if only one destination succeeds; report the successful destination and the remaining blocker explicitly.

GitLab and GitHub may have unrelated or independently advanced `main` histories. Never merge private GitLab-only history into public GitHub. In that case, publish the reviewed tag commit to both remotes, advance GitHub `main` only from its public history, and reconcile GitLab `main` locally on GitLab. The resulting GitLab `main` tree must exactly match the tagged release tree even if its integration commit differs.

## Release procedure

1. Fetch both remotes and inspect their current `main` branches, tags, and releases.
2. Work from a clean isolated checkout based on the newest reviewed release lineage. Never sweep unrelated dirty or untracked files from another checkout into a release.
3. Review the exact release delta. Update `VERSION`, add `docs/RELEASE-<version>.md`, update relevant README and audit text, and keep personal paths, credentials, logs, and board state out of Git.
4. Run the complete test suite, Python and embedded-JavaScript syntax checks, `git diff --check`, secret/path scans, and clean-profile checks.
5. Build the Apple Silicon app, verify bundled source equality and `codesign --verify --deep --strict`, package the ZIP, test extraction, and record its SHA-256. GitLab may use a `.tar.xz` only if its ZIP endpoint rejects the exact ZIP.
6. Create one release commit and one annotated tag. Push the exact tagged commit and tag to GitLab and GitHub without force-pushing. If their `main` histories differ, use the safe reconciliation rule above instead of publishing private ancestry to GitHub.
7. Publish release pages and artifacts to both services. GitLab assets should use its generic package registry; GitHub assets should use GitHub Releases.
8. Read back both remote `main` refs and tree IDs, tag dereferences, tagged `VERSION`, release metadata, and asset lists. Both `main` trees must match the tagged release tree. Download each published artifact independently and compare its SHA-256 with the reviewed local package.
9. Report the shared commit, tag, release URLs, artifact checksum, verification results, and any limitation. A successful upload alone is not completion.

Preserve recoverable local backups when replacing an installed app. Do not modify the user's other working checkout while creating an isolated release.
