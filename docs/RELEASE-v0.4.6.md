# Agent Board v0.4.6

Explicit chat closeouts now behave like the board's reversible **Session done** action.

- Short commands such as `done`, `ok done`, and `mark this session done` move the session to **Completed**.
- Questions, negations, and longer messages containing a new request remain open.
- A later substantive message reopens the session through the existing timestamp rule.
- Details identify chat-driven completion as **Confirmed from chat**, and Undo remains available.
- The fallback classifier promotes missed closeouts directly to completion instead of displaying a contradictory suggestion.
- A one-time migration repairs any `chat_done` suggestion written by the v0.4.6 development build.

Regression tests cover accepted closeouts, questions and negations, follow-up requests, Stop-hook persistence, fallback cleanup, and existing Claude activity-state behavior.

## Installation

- Download **Agent Board v0.4.6 for Apple Silicon (.zip)** from the release page, unzip it, and open `Agent Board.app`.
- Verify SHA-256: `b10a0cf8eb4ce60c88786b499d6c3e87e8acdad7119991970aa738de54304f6e`.
- The ready-built app requires neither Python, SwiftBar, Xcode Command Line Tools, nor `uvx`.
- The app targets Apple Silicon and macOS 13 or later. It is locally signed and not Apple-notarized, so macOS may require **Open Anyway** in System Settings → Privacy & Security.
- Updates remain manual; Agent Board does not silently replace itself.
