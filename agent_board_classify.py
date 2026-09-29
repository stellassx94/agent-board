#!/usr/bin/python3
"""Record Agent Board state after a Claude/Codex turn.

This is a Stop-hook side effect. Suggestions never change a user's board
choice, while a short explicit chat closeout records the same reversible
completion marker as the board button. The hook never blocks a turn.
"""

import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENT_BOARD_DATA_DIR", "~/.agent-board")).expanduser()
OUT = Path(os.environ.get("AGENT_BOARD_SUGGESTIONS_FILE", str(DATA_DIR / "agent_board_suggestions.json"))).expanduser()
COMPLETED_OUT = Path(os.environ.get("AGENT_BOARD_COMPLETED_FILE", str(DATA_DIR / "agent_board_completed.json"))).expanduser()
FLAGS_OUT = Path(os.environ.get("AGENT_BOARD_FLAGS_FILE", str(DATA_DIR / "agent_board_flags.json"))).expanduser()
PROMPTS_OUT = Path(os.environ.get("AGENT_BOARD_PROMPTS_FILE", str(DATA_DIR / "agent_board_prompts.json"))).expanduser()
PROMPT_KEEP_SECONDS = 7 * 86400
MAX_TAIL = 1_000_000
CONTINUE = re.compile(r"\b(next steps?|remaining|still need|pending|blocked by|waiting for|follow[ -]?up|to continue|not yet|needs your|need you to|once (?:you|we) (?:have|confirm|provide)|after (?:you|we) (?:have|confirm|provide))\b", re.I)
DONE = re.compile(r"\b(completed|implemented|fixed|updated|created|saved|verified|delivered|finished|resolved|published|ready)\b", re.I)
QUESTION = re.compile(r"\b(?:please|could you|would you|can you|do you|which|what|when|where|how)\b[^?\n]{0,180}\?\s*$", re.I)
ONE_OFF = re.compile(r"^(?:what|who|when|where|why|how|is|are|can|does|do|translate|rewrite|summarize)\b", re.I)
SYSTEM_MARKERS = ("<recommended_plugins>", "<environment_context>", "<skills_instructions>", "The following is the Codex agent history")
PARK = re.compile(r"(?:continue later|(?:let's|we can|please|i will|i'll) continue later|pause (?:this|the session) and continue later)", re.I)
CLOSEOUT = re.compile(
    r"(?:"
    r"done|all done|"
    r"(?:(?:ok(?:ay)?|yes|yep|great|thanks|thank you)[, ]+)(?:all )?done|"
    r"(?:we(?:'re| are)|it(?:'s| is)|this (?:session|task) is|the (?:session|task) is) done|"
    r"mark (?:this |the )?(?:session|task) (?:as )?done|"
    r"close (?:this |the )?(?:session|task)"
    r")",
    re.I,
)


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(x.get("text", "") for x in value if isinstance(x, dict) and x.get("type") in ("text", "input_text", "output_text"))
    return ""


def latest_user_event(path):
    if not path or not Path(path).is_file():
        return "", None
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
            try:
                when = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()
            except (KeyError, TypeError, ValueError):
                when = None
            return value[:1000], when
    return "", None


def latest_user(path):
    return latest_user_event(path)[0]


def is_explicit_closeout(value):
    """Recognize only short, unambiguous user commands to close this session."""
    if not isinstance(value, str) or "?" in value:
        return False
    normalized = value.replace("’", "'")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or len(normalized) > 80:
        return False
    normalized = normalized.rstrip(".! ")
    return bool(CLOSEOUT.fullmatch(normalized))


def is_explicit_park(value):
    """Only short user closeouts can park a session automatically."""
    if not isinstance(value, str) or "?" in value:
        return False
    normalized = re.sub(r"\s+", " ", value.replace("’", "'")).strip().rstrip(".! ")
    return bool(normalized and len(normalized) <= 80 and PARK.fullmatch(normalized))


def classify(hook):
    answer = re.sub(r"\s+", " ", hook.get("last_assistant_message") or "").strip()
    user = latest_user(hook.get("transcript_path"))
    if hook.get("background_tasks") or hook.get("session_crons"):
        return "continue", "Background or scheduled work is still in progress."
    if not answer:
        return "uncertain", "No final reply was available to assess."
    if is_explicit_park(user):
        return "chat_parked", "You explicitly saved this session for later in chat."
    if is_explicit_closeout(user):
        return "chat_done", "You explicitly marked this session done in chat."
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


def save_completion(sid, source="chat-closeout", at=None, user_at=None):
    """Persist a reversible, timestamp-bound completion marker."""
    COMPLETED_OUT.parent.mkdir(parents=True, exist_ok=True)
    lock_path = COMPLETED_OUT.with_suffix(".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(COMPLETED_OUT.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        if source == "chat-parked" and user_at is not None:
            previous = data.get(sid) or {}
            if (previous.get("source") in ("board-undone", "chat-parked") and
                    previous.get("at", 0) >= user_at):
                return False
        data[sid] = {"at": time.time() if at is None else at, "source": source}
        tmp = COMPLETED_OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(COMPLETED_OUT)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def save_parked(sid, at=None, user_at=None):
    """Mark this session finished and keep its workstream starred for resumption."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        raise ValueError("invalid session id")
    stamp = time.time() if at is None else at
    if not save_completion(sid, source="chat-parked", at=stamp, user_at=user_at):
        return False
    FLAGS_OUT.parent.mkdir(parents=True, exist_ok=True)
    lock_path = FLAGS_OUT.with_suffix(".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            flags = json.loads(FLAGS_OUT.read_text())
            if not isinstance(flags, dict):
                flags = {}
        except (OSError, ValueError):
            flags = {}
        # Preserve a note or earlier star rather than resetting it on a repeat hook.
        flags.setdefault(sid, {"note": "", "at": stamp})
        tmp = FLAGS_OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(flags, indent=1, ensure_ascii=False))
        tmp.replace(FLAGS_OUT)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def clear_suggestion(sid):
    """Remove a fallback suggestion after promoting it to completion."""
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
        data.pop(sid, None)
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(OUT)
        fcntl.flock(lock, fcntl.LOCK_UN)


def save_prompt(hook):
    """Record a Claude Code permission prompt from a Notification hook."""
    sid = str(hook.get("session_id") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        return False
    message = str(hook.get("message") or "")
    kind = hook.get("notification_type")
    if kind != "permission_prompt" and not (kind is None and "permission" in message.lower()):
        return False
    PROMPTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    lock_path = PROMPTS_OUT.with_suffix(".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(PROMPTS_OUT.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        now = time.time()
        data = {k: v for k, v in data.items()
                if isinstance(v, dict) and now - v.get("at", 0) < PROMPT_KEEP_SECONDS}
        data[sid] = {"at": now, "message": message[:180]}
        tmp = PROMPTS_OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(PROMPTS_OUT)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def capture_prompt():
    try:
        save_prompt(json.load(sys.stdin))
    except Exception:
        # A board marker must never interrupt Claude's notification lifecycle.
        pass


def main():
    if "capture-prompt" in sys.argv[1:]:
        capture_prompt()
        return
    try:
        hook = json.load(sys.stdin)
        sid = str(hook.get("session_id") or "")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
            return
        state, reason = classify(hook)
        if "--dry-run" in sys.argv:
            print(json.dumps({"id": sid, "state": state, "reason": reason}))
        elif state == "chat_done":
            save_completion(sid)
        elif state == "chat_parked":
            _, user_at = latest_user_event(hook.get("transcript_path"))
            save_parked(sid, user_at=user_at)
            clear_suggestion(sid)
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
