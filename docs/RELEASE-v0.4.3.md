# Agent Board v0.4.3

This release keeps the reviewed v0.4.1 design and improves Codex question status.

- An unanswered Codex question stays in **Asking you** after the asynchronous question tool returns.
- The pending question clears when you reply or the Codex turn ends.
- A pending question remains visible even after the session passes the idle timeout.

Done, Continue later, Temporary, Dismiss, and workstream completion remain manual choices. Idle activity is never treated as completion.

The Mac app targets Apple Silicon and macOS 13 or later. It is locally signed and not notarized. The Releases page is a manual check; the app does not download or install updates automatically.
