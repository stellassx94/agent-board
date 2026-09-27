#!/usr/bin/python3
"""Record a conservative Agent Board suggestion after a Claude/Codex turn.

This is a Stop-hook side effect. It never changes a user's board choice and
never blocks a turn. Suggestions are intentionally separate from completion.
"""

import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENT_BOARD_DATA_DIR", "~/.agent-board")).expanduser()
OUT = Path(os.environ.get("AGENT_BOARD_SUGGESTIONS_FILE", str(DATA_DIR / "agent_board_suggestions.json"))).expanduser()
MAX_TAIL = 1_000_000
CONTINUE = re.compile(r"\b(next steps?|remaining|still need|pending|blocked by|waiting for|follow[ -]?up|to continue|not yet|needs your|need you to|once (?:you|we) (?:have|confirm|provide)|after (?:you|we) (?:have|confirm|provide))\b", re.I)
DONE = re.compile(r"\b(completed|implemented|fixed|updated|created|saved|verified|delivered|finished|resolved|published|ready)\b", re.I)
QUESTION = re.compile(r"\b(?:please|could you|would you|can you|do you|which|what|when|where|how)\b[^?\n]{0,180}\?\s*$", re.I)
ONE_OFF = re.compile(r"^(?:what|who|when|where|why|how|is|are|can|does|do|translate|rewrite|summarize)\b", re.I)
SYSTEM_MARKERS = ("<recommended_plugins>", "<environment_context>", "<skills_instructions>", "The following is the Codex agent history")


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(x.get("text", "") for x in value if isinstance(x, dict) and x.get("type") in ("text", "input_text", "output_text"))
    return ""


def latest_user(path):
    if not path or not Path(path).is_file():
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - MAX_TAIL))
        lines = f.read().splitlines()
    if size > MAX_TAIL:
        lines = lines[1:]
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        payload = row.get("payload") or {}
        value = ""
        if row.get("type") == "user" and not row.get("isSidechain"):
            value = text_content((row.get("message") or {}).get("content"))
            if "tool_result" in str((row.get("message") or {}).get("content", ""))[:100]:
                continue
        elif row.get("type") == "event_msg" and payload.get("type") == "user_message":
            value = payload.get("message") or ""
        elif row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
            value = text_content(payload.get("content"))
        value = re.sub(r"\s+", " ", value).strip()
        if value and not any(marker in value for marker in SYSTEM_MARKERS):
            return value[:1000]
    return ""


def classify(hook):
    answer = re.sub(r"\s+", " ", hook.get("last_assistant_message") or "").strip()
    user = latest_user(hook.get("transcript_path"))
    if hook.get("background_tasks") or hook.get("session_crons"):
        return "continue", "Background or scheduled work is still in progress."
    if not answer:
        return "uncertain", "No final reply was available to assess."
    # A question at the end is a request for the user's next move.
    if QUESTION.search(answer[-300:]):
        return "waiting", "The reply ends with a question for you."
    # Look near the conclusion; broad mentions of a limitation earlier in a
    # report are not enough to label the whole session as pending.
    match = CONTINUE.search(answer[-700:])
    if match:
        return "continue", "The reply mentions an open follow-up (" + match.group(0).lower() + ")."
    if ONE_OFF.match(user) and user.rstrip().endswith("?") and len(user) < 120 and not DONE.search(answer):
        return "temporary", "The latest request looks like a short one-off question."
    if DONE.search(answer):
        return "likely_done", "The reply reports delivered work; please confirm completion."
    return "uncertain", "The reply gives no clear completion or follow-up signal."


def save(sid, state, reason, source="stop-hook-rules"):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lock_path = OUT.with_suffix(".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(OUT.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[sid] = {"state": state, "reason": reason[:180], "at": time.time(), "source": source}
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(OUT)
        fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    try:
        hook = json.load(sys.stdin)
        sid = str(hook.get("session_id") or "")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
            return
        state, reason = classify(hook)
        if "--dry-run" in sys.argv:
            print(json.dumps({"id": sid, "state": state, "reason": reason}))
        else:
            save(sid, state, reason)
    except Exception:
        # A board suggestion must never interrupt the agent's Stop lifecycle.
        pass
    finally:
        if "--dry-run" not in sys.argv:
            print("{}")  # Codex Stop requires JSON on stdout.


if __name__ == "__main__":
    main()
