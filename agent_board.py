#!/usr/bin/env python3
"""Agent Board — local live view of Claude Code and Codex workstreams.

Reads local session logs and serves a page on http://127.0.0.1:8765.
User data and optional configuration live outside this source directory.
"""
import argparse
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
import agent_board_workstreams as ws
import agent_board_classify as turn_classifier

DATA_DIR = Path(os.environ.get("AGENT_BOARD_DATA_DIR", "~/.agent-board")).expanduser()
CONFIG_FILE = Path(os.environ.get("AGENT_BOARD_CONFIG", str(DATA_DIR / "config.json"))).expanduser()


def load_config():
    if not CONFIG_FILE.exists():
        return {}
    config = json.loads(CONFIG_FILE.read_text())
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_FILE} must contain a JSON object")
    return config


CONFIG = load_config()
ROOTS = [Path(p).expanduser() for p in CONFIG.get("claude_roots", ["~/.claude/projects"])]
CODEX_DIR = Path(CONFIG.get("codex_dir", "~/.codex")).expanduser()


def source_version():
    version_file = Path(__file__).with_name("VERSION")
    try:
        return version_file.read_text().strip()
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["/usr/bin/git", "describe", "--tags", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
            timeout=2, check=True,
        )
        return result.stdout.strip() or "local copy"
    except (OSError, subprocess.SubprocessError):
        return "local copy"


BOARD_VERSION = source_version()
TAIL_BYTES = 1_000_000
STUCK_MIN = 15          # a tool running longer than this is flagged
QUIET_MIN = 5           # no log writes for this long while "thinking" is flagged
ABANDONED_MIN = 120     # quiet longer than this and not finished = abandoned, not stuck
YOUR_TURN_HOURS = 3    # finished within this window = "your turn", older = idle
SUGGESTION_REVIEW_HOURS = 72  # unreviewed completion and temporary suggestions expire
COMMON_TOKENS = {"run_query.py", "scripts/run_query.py", ".presto_creds.env", "presto_creds.env",
                 "shell-snapshots", "NO_EXTENDED_GLOB", "NO_BARE_GLOB_QUAL", "/dev/null"}

_cache = {}
_fallback_cache = {}
_recent_status = None


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def ps_snapshot():
    try:
        out = subprocess.run(["ps", "-axo", "pid,etime,command"], capture_output=True, text=True).stdout
    except Exception:
        return [], 0
    lines = out.splitlines()[1:]
    n_claude = sum(1 for l in lines if "native-binary/claude " in l or re.search(r"(^|\s|/)claude( --|$)", l.split(None, 2)[-1]))
    return lines, n_claude


def cmd_tokens(cmd):
    toks = set(re.findall(r"[\w./-]{12,}", cmd or ""))
    return [t for t in toks if t not in COMMON_TOKENS and "Users/" not in t and "CloudStorage" not in t
            and "claude-working-folder" not in t and not t.startswith("/opt/") and not t.startswith("/usr/")]


def command_alive(cmd, ps_lines):
    toks = cmd_tokens(cmd)
    if not toks:
        return None
    others = [l for l in ps_lines if "native-binary/claude" not in l and "agent_board.py" not in l]
    return any(t in l for t in toks for l in others)


def short(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_label(name, inp):
    inp = inp or {}
    if name == "Bash":
        return inp.get("description") or short(inp.get("command", ""), 120)
    if name in ("Agent", "Task"):
        return "subagent: " + (inp.get("description") or "")
    for k in ("file_path", "path", "pattern", "query", "url", "skill"):
        if inp.get(k):
            return f"{k}: {short(str(inp[k]), 100)}"
    return ""


def first_claude_prompt(data):
    """Use the opening user request as a stable fallback title."""
    for raw in io.BytesIO(data):
        if b'"type":"user"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, list):
            content = " ".join(block.get("text", "") for block in content
                               if isinstance(block, dict) and block.get("type") == "text")
        if isinstance(content, str):
            content = content.strip()
            if content and not content.startswith(("<task-notification>", "<local-command")):
                return content
    return None


def synthetic_user_event(row, content):
    """Return True for Claude control records serialized as user messages.

    Claude uses user-shaped transcript rows to deliver background-task and
    local-command notifications. They are useful for bookkeeping, but they do
    not mean that a person started a new turn.
    """
    origin = row.get("origin") or {}
    if origin.get("kind") == "task-notification" or row.get("turnOrigin") == "task_notification":
        return True
    if not isinstance(content, str):
        return False
    return content.lstrip().startswith(("<task-notification>", "<local-command"))


def assistant_turn_finished(row, message):
    """Recognize terminal assistant records that are not normal end_turns."""
    if row.get("isApiErrorMessage") or row.get("error"):
        return True
    return message.get("stop_reason") in {"end_turn", "stop_sequence", "max_tokens", "refusal"}


def parse_session(path):
    st = path.stat()
    sub = path.with_suffix("")  # sibling folder with subagent logs
    act = st.st_mtime
    if sub.is_dir():
        for p in sub.rglob("*.jsonl"):
            try:
                act = max(act, p.stat().st_mtime)
            except OSError:
                pass
    key = (st.st_mtime, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        info = dict(hit[1])
        # A transcript can be touched by reconnect, bridge, or cost metadata.
        # Only meaningful conversation events should refresh board activity.
        info["activity"] = info["last_ts"] or act
        return info

    with open(path, "rb") as f:
        data = f.read()
    title = None
    first_prompt = first_claude_prompt(data)
    i = data.rfind(b'"aiTitle":"')
    if i >= 0:
        try:
            title = json.loads(data[data.rfind(b"\n", 0, i) + 1: data.find(b"\n", i)])["aiTitle"]
        except Exception:
            pass
    m = re.search(rb'"cwd":"((?:[^"\\]|\\.)*)"', data)
    start_cwd = json.loads(b'"' + m.group(1) + b'"') if m else None
    m = re.search(rb'"entrypoint":"([A-Za-z0-9_-]{1,40})"', data)
    entrypoint = m.group(1).decode() if m else None
    tail = data[-TAIL_BYTES:]
    lines = tail.split(b"\n")
    if len(data) > TAIL_BYTES:
        lines = lines[1:]

    pending = {}
    bg = {}  # background jobs started by this session, keyed by tool_use id
    last_kind, last_ts, last_text, last_prompt, cwd = None, None, "", None, None
    last_user, last_user_ts = "", None
    for raw in lines:
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        t = d.get("type")
        note = d.get("content") if t == "queue-operation" else None
        if t == "user" and isinstance((d.get("message") or {}).get("content"), str):
            note = d["message"]["content"]
        if note and "<task-notification>" in note:
            for tid in re.findall(r"<tool-use-id>([^<]+)</tool-use-id>", note):
                bg.pop(tid, None)
        if t == "last-prompt":
            last_prompt = d.get("lastPrompt")
        if t == "ai-title" and not title:
            title = d.get("aiTitle")
        if t not in ("user", "assistant", "system") or d.get("isSidechain"):
            continue
        cwd = d.get("cwd") or cwd
        when = ts(d.get("timestamp", "")) or last_ts
        if t == "system":
            if d.get("subtype") == "stop_hook_summary":
                last_kind, last_ts = "done", when
                pending.clear()
            continue
        content = (d.get("message") or {}).get("content")
        if t == "user":
            if synthetic_user_event(d, content):
                continue
            if isinstance(content, list):
                user_text = turn_classifier.text_content(content).strip()
                if user_text and not any(marker in user_text for marker in turn_classifier.SYSTEM_MARKERS):
                    last_user, last_user_ts = user_text, when
                for b in content:
                    if b.get("type") == "tool_result":
                        tid = b.get("tool_use_id")
                        pending.pop(tid, None)
                        if tid in bg and not re.search(r"background|launched|async", str(b.get("content"))[:600], re.I):
                            bg.pop(tid, None)  # finished in the foreground
                last_kind, last_ts = "thinking", when
            elif isinstance(content, str):
                if "[Request interrupted" in content:
                    last_kind = "done"
                    pending.clear()
                else:
                    last_kind = "thinking"
                last_ts = when
                if not any(marker in content for marker in turn_classifier.SYSTEM_MARKERS):
                    last_user, last_user_ts = content, when
        else:
            msg = d.get("message") or {}
            for b in content or []:
                if b.get("type") == "tool_use":
                    pending[b["id"]] = (b.get("name"), b.get("input"), when)
                    if (b.get("input") or {}).get("run_in_background") or b.get("name") in ("Agent", "Task"):
                        bg[b["id"]] = (b.get("name"), b.get("input"), when)
                elif b.get("type") == "text" and b.get("text", "").strip():
                    last_text = b["text"]
            last_kind = "tool" if pending else ("done" if assistant_turn_finished(d, msg) else "thinking")
            last_ts = when

    info = {
        "id": path.stem,
        "title": short(title or first_prompt or "", 80) or path.stem[:8],
        "project": Path(start_cwd or cwd).name if (start_cwd or cwd) else path.parent.name.split("-")[-1],
        "root": path.parent.parent.parent.name,
        "cwd": start_cwd or cwd,
        "entrypoint": entrypoint,
        "last_kind": last_kind,
        "last_ts": last_ts,
        "last_user": last_user,
        "last_user_ts": last_user_ts,
        "last_text": short(last_text, 220),
        "last_reply": last_text,
        "pending": [{"name": n, "label": tool_label(n, i), "cmd": (i or {}).get("command", ""), "ts": w}
                    for n, i, w in pending.values()],
        "activity": last_ts or act,
        "bg": [{"name": n, "label": tool_label(n, i), "cmd": (i or {}).get("command", ""), "ts": w}
               for n, i, w in bg.values()],
    }
    _cache[path] = (key, info)
    return info


ASK_TOOLS = ("AskUserQuestion", "ExitPlanMode", "request_user_input", "request_user_input_async")
APPROVAL_GRACE_SECONDS = 10
BG_STUCK_MIN = 45       # a background job longer than this is flagged
BG_EXPIRE_MIN = 240     # background jobs older than this are ignored (notification likely missed)


def live_bg(s, now, ps_lines):
    out = []
    for j in s.get("bg") or []:
        age = (now - (j["ts"] or now)) / 60
        if age > BG_EXPIRE_MIN:
            continue
        if j["name"] == "Bash" and command_alive(j["cmd"], ps_lines) is False:
            continue
        out.append({**j, "age": age})
    return out


def classify(s, now, ps_lines):
    quiet = (now - s["activity"]) / 60
    jobs = live_bg(s, now, ps_lines)
    asking = [p for p in s["pending"] if p["name"] in ASK_TOOLS]
    if asking:
        return "asking", "Asking you a question. Open the session to answer."
    possible_approval = [p for p in s["pending"] if p["name"] == "codex_approval"
                         and now - (p["ts"] or now) >= APPROVAL_GRACE_SECONDS]
    if possible_approval:
        return "asking", "May be awaiting approval. Open the session to check."
    if quiet > ABANDONED_MIN and s["last_kind"] != "done" and not jobs:
        return "idle", "Stopped mid-step. No activity for a long time."
    if jobs and s["last_kind"] == "done":
        j = max(jobs, key=lambda x: x["age"])
        what = f"{j['name']}: {j['label']}"
        if j["age"] > BG_STUCK_MIN:
            return "check", f"Background job running for {j['age']:.0f} min. {what}"
        return "running", f"Waiting for background job ({j['age']:.0f} min). {what}"
    if s["last_kind"] == "done" or s["last_kind"] is None:
        if now - s["activity"] < YOUR_TURN_HOURS * 3600:
            return "yourturn", "Finished. Waiting for you."
        return "idle", "Idle."
    if s["pending"]:
        p = max(s["pending"], key=lambda x: x["ts"] or 0)
        age = (now - (p["ts"] or now)) / 60
        alive = command_alive(p["cmd"], ps_lines) if p["name"] == "Bash" else None
        what = f"{p['name']}: {p['label']}"
        if p["name"] == "Bash" and alive is False and age > 1:
            return "check", f"Command is no longer running, but the session did not continue ({age:.0f} min). {what}"
        if age > STUCK_MIN:
            extra = " Process still alive." if alive else ""
            return "check", f"Running for {age:.0f} min.{extra} {what}"
        return "running", f"Running for {age:.0f} min. {what}" + ("" if alive is not False else " (may be waiting for your approval)")
    if quiet > QUIET_MIN:
        return "check", f"No activity for {quiet:.0f} min. Session may be closed or stuck."
    return "working", "Thinking / writing."


def ps_tree():
    try:
        out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,etime=,command="], capture_output=True, text=True).stdout
    except Exception:
        return []
    rows = []
    for l in out.splitlines():
        p = l.split(None, 3)
        if len(p) == 4 and p[0].isdigit() and p[1].isdigit():
            rows.append((int(p[0]), int(p[1]), p[2], p[3]))
    return rows


def etime_min(e):
    days, _, hms = e.rpartition("-")
    parts = [int(x) for x in hms.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]) / 60


SHELL_RE = re.compile(r"^(/bin/|/usr/bin/)?(zsh|bash|sh)\b|^\(?(sleep|wait|tee|u?grep|head|tail|cat|sed|awk|tr|cut|sort|uniq|wc|xargs|ps|date|ls|echo)\b")


def worker_label(cmd):
    m = re.search(r"run_query\.py.*?--query\s+(\S+)", cmd)
    if m:
        return os.path.basename(m.group(1))
    m = re.search(r"([^/]+)\.app/", cmd)
    if m:
        return m.group(1)
    parts = cmd.split()
    return short(" ".join([os.path.basename(parts[0])] + parts[1:3]), 60) if parts else ""


def job_progress(cmd, tree):
    """For a running Bash job: which child processes still run, and how many loop items are done."""
    key = re.sub(r"\s+", "", (cmd or "").replace("'", "'\\''"))[:200]
    if len(key) < 20 or not tree:
        return ""
    shells = {pid for pid, _, _, c in tree
              if "eval" in c and "agent_board.py" not in c and key in re.sub(r"\s+", "", c)}
    if not shells:
        return ""
    kids, seen = {}, set(shells)
    for pid, ppid, _, _ in tree:
        kids.setdefault(ppid, []).append(pid)
    stack, desc = list(shells), []
    while stack:
        for k in kids.get(stack.pop(), []):
            if k not in seen:
                seen.add(k)
                desc.append(k)
                stack.append(k)
    byid = {pid: (e, c) for pid, _, e, c in tree}
    workers = [(worker_label(byid[p][1]), etime_min(byid[p][0])) for p in desc
               if p in byid and not SHELL_RE.search(byid[p][1]) and "native-binary/claude" not in byid[p][1]]
    grouped = {}
    for n, m in workers:
        c, old = grouped.get(n, (0, 0))
        grouped[n] = (c + 1, max(old, m))
    run = ", ".join(f"{n}{f' ×{c}' if c > 1 else ''} ({m:.0f} min)"
                    for n, (c, m) in sorted(grouped.items(), key=lambda w: -w[1][1])[:6])
    loop = re.search(r"for\s+\w+\s+in\s+([^;\n]+?)\s*;?\s*do\b(.*?)\bdone", cmd, re.S)
    if loop and re.search(r"[^&]&(?!&)", loop.group(2)):
        items = [x for x in loop.group(1).split() if not re.search(r"[$*`]", x)]
        if items and len(workers) <= len(items):
            done = len(items) - len(workers)
            return f"{done} of {len(items)} done." + (f" Still running: {run}" if run else "")
    return f"Still running: {run}" if run else ""


def hint(state, detail):
    if state != "check":
        return ""
    if detail.startswith("Background job"):
        return "Big queries can be slow. Wait. If it is still red in 30 min, open the session and ask it to stop and rerun the slow part."
    if detail.startswith("Command is no longer running"):
        return "Open the session and type \"continue\". The command ended, but the session did not see it."
    if detail.startswith("Running for"):
        return "Open the session. It may wait for your approval. If the command hangs, press Esc and ask it to retry."
    if detail.startswith("No activity"):
        return "Open the session. If it is closed, start a new one and run /resume."
    return "Open the session and check it."


_codex_titles = {"mtime": 0, "map": {}}


def codex_titles():
    idx = CODEX_DIR / "session_index.jsonl"
    try:
        m = idx.stat().st_mtime
    except OSError:
        return {}
    if m != _codex_titles["mtime"]:
        mp = {}
        with open(idx, "rb") as f:  # index is large; recent threads are appended at the end
            f.seek(max(0, idx.stat().st_size - 3_000_000))
            tail = f.read().decode("utf-8", "ignore")
        for line in tail.splitlines()[1:]:
            try:
                d = json.loads(line)
                mp[d["id"]] = d.get("thread_name")
            except Exception:
                pass
        _codex_titles.update(mtime=m, map=mp)
    return _codex_titles["map"]


def codex_first_user_message(data):
    """Find the first actual prompt, skipping injected app and workspace context."""
    for raw in data.splitlines():
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        payload = record.get("payload") or {}
        candidates = []
        if record.get("type") == "event_msg" and payload.get("type") == "user_message":
            candidates = [payload.get("message")]
        elif (record.get("type") == "response_item" and payload.get("type") == "message"
              and payload.get("role") == "user"):
            candidates = [item.get("text") for item in payload.get("content") or []
                          if isinstance(item, dict) and item.get("type") == "input_text"]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if candidate and not candidate.startswith(("<recommended_plugins>",
                                                       "# AGENTS.md instructions",
                                                       "<environment_context>")):
                return candidate
    return None


def codex_escalated_call(name, args):
    if name == "exec_command":
        try:
            return json.loads(args).get("sandbox_permissions") == "require_escalated"
        except (TypeError, ValueError, AttributeError):
            return False
    if name == "exec":
        return bool(re.search(
            r"""\btools\.exec_command\s*\(\s*\{.*?\bsandbox_permissions\s*:\s*["']require_escalated["']""",
            args, re.S))
    return False


def parse_codex(path):
    st = path.stat()
    key = (st.st_mtime, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    with open(path, "rb") as f:
        data = f.read()
    lines = data[-TAIL_BYTES:].split(b"\n")
    if len(data) > TAIL_BYTES:
        lines = lines[1:]
    sid, cwd, first_msg, originator = path.stem[-36:], None, None, None
    head = data[: data.find(b"\n")] if b"\n" in data else data
    try:
        meta = json.loads(head)["payload"]
        sid, cwd = meta.get("id", sid), meta.get("cwd")
        originator = meta.get("originator")
        if meta.get("parent_thread_id"):  # helper/subagent thread, not a user session
            _cache[path] = (key, None)
            return None
    except Exception:
        pass
    pending = {}
    awaiting_question = None
    last_kind, last_ts, last_text = None, None, ""
    last_user, last_user_ts = "", None
    for raw in lines:
        try:
            d = json.loads(raw)
        except Exception:
            continue
        p = d.get("payload") or {}
        pt = p.get("type") or ""
        when = ts(d.get("timestamp", "")) or last_ts
        if d.get("type") == "event_msg":
            if pt in ("task_started", "user_message"):
                last_kind, last_ts = "thinking", when
                if pt == "user_message":
                    awaiting_question = None
                    last_user, last_user_ts = p.get("message") or "", when
                    pending = {call_id: item for call_id, item in pending.items()
                               if item[0] != "codex_approval"}
                if pt == "user_message" and not first_msg:
                    first_msg = p.get("message")
            elif pt in ("task_complete", "turn_aborted"):
                last_kind, last_ts = "done", when
                pending.clear()
                awaiting_question = None
                last_text = p.get("last_agent_message") or last_text
            elif pt == "agent_message":
                last_text, last_ts = p.get("message") or last_text, when
        elif d.get("type") == "response_item" and pt == "message" and p.get("role") == "user":
            user_text = turn_classifier.text_content(p.get("content")).strip()
            if user_text and not any(marker in user_text for marker in turn_classifier.SYSTEM_MARKERS):
                last_user, last_user_ts = user_text, when
        elif d.get("type") == "response_item" and p.get("call_id"):
            if pt.endswith("_call_output"):
                pending.pop(p["call_id"], None)
            elif pt.endswith("_call"):
                args = p.get("arguments") or p.get("input") or ""
                name = p.get("name") or pt
                if codex_escalated_call(name, args):
                    name, label = "codex_approval", "Possible approval request"
                else:
                    label = short(str(args), 100)
                pending[p["call_id"]] = (name, label, when)
                if p.get("name") == "request_user_input_async":
                    awaiting_question = ("request_user_input_async", "Awaiting your answer", when)
            if last_kind != "done":
                last_kind, last_ts = ("tool" if pending else "thinking"), when
    first_msg = codex_first_user_message(data) or first_msg
    pending_items = list(pending.values())
    if awaiting_question and not any(n == "request_user_input_async" for n, _, _ in pending_items):
        pending_items.append(awaiting_question)
    info = {
        "id": sid,
        "title": codex_titles().get(sid) or short(first_msg or "", 80) or sid[:8],
        "project": Path(cwd).name if cwd else "codex",
        "root": "codex",
        "originator": originator,
        "cwd": cwd,
        "last_kind": last_kind,
        "last_ts": last_ts,
        "last_user": last_user,
        "last_user_ts": last_user_ts,
        "last_text": short(last_text, 220),
        "last_reply": last_text,
        "pending": [{"name": n, "label": lbl, "cmd": "", "ts": w} for n, lbl, w in pending_items],
        "activity": last_ts if last_kind == "done" and last_ts else st.st_mtime,
    }
    _cache[path] = (key, info)
    return info


CLAUDE_APP_SESSIONS = Path.home() / "Library/Application Support/Claude/claude-code-sessions"


def claude_app_titles():
    """Read Claude Desktop titles once per board status request."""
    titles = {}
    for path in CLAUDE_APP_SESSIONS.glob("*/*/local_*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        sid, title = data.get("cliSessionId"), data.get("title")
        if isinstance(sid, str) and isinstance(title, str) and title.strip():
            titles[sid] = title.strip()
    return titles


def claude_display_title(path, parsed_title, app_titles):
    """Prefer Claude's saved custom title, then its app title."""
    try:
        data = json.loads((path.with_suffix("") / "custom-title.json").read_text())
        custom = data.get("customTitle")
        if isinstance(custom, str) and custom.strip():
            return short(custom, 80)
    except (OSError, ValueError):
        pass
    return short(app_titles.get(path.stem) or parsed_title, 80)


RESUME_TITLE_RE = re.compile(r"(?i)^\s*(?:/?resume|use the resume skill)\b(?:.*?\b([0-9a-f]{8})[0-9a-f-]*)?")


def inherit_resume_titles(rows, links):
    """Replace "Resume session <id>" titles with the title of the resumed session."""
    by_id = {r["id"]: r for r in rows}

    def generic(title):
        m = RESUME_TITLE_RE.match(title or "")
        return m if m and (m.group(1) or not title.strip(" /").lower().replace("resume", "")) else None

    def source_of(r):
        parent = (links.get(r["id"]) or {}).get("parent")
        if parent in by_id:
            return by_id[parent]
        m = generic(original[r["id"]])
        prefix = m.group(1) if m else None
        return next((x for x in rows if prefix and x is not r and x["id"].startswith(prefix)), None)

    original = {r["id"]: r["title"] for r in rows}
    for r in rows:
        if not generic(original[r["id"]]):
            continue
        seen, src = {r["id"]}, source_of(r)
        while src and generic(original[src["id"]]) and src["id"] not in seen:
            seen.add(src["id"])
            src = source_of(src)
        if src and not generic(original[src["id"]]):
            r["title"] = short("↩ " + original[src["id"]].lstrip("↩ "), 80)


def claude_app_session_id(cli_sid):
    """Resolve a Claude Desktop session from its Claude Code transcript ID."""
    for path in CLAUDE_APP_SESSIONS.glob("*/*/local_*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        app_sid = data.get("sessionId")
        if (data.get("cliSessionId") == cli_sid and isinstance(app_sid, str)
                and re.fullmatch(r"local_[A-Za-z0-9-]{1,64}", app_sid)):
            return app_sid
    return None


def open_session(sid, hours):
    """Open Claude app sessions in Claude, or use the configured local target."""
    snapshot = _recent_status
    row = next((r for r in snapshot[2] if r["id"] == sid), None) if snapshot else None
    if row is None:
        row = next((r for r in status(hours)["sessions"] if r["id"] == sid), None)
    if not row:
        return False
    if sys.platform == "darwin" and row["root"] == "codex" and row.get("originator") == "Codex Desktop":
        try:
            subprocess.run(["open", f"codex://threads/{sid}"], check=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return False
        return True
    if sys.platform == "darwin" and row["root"] != "codex":
        app_sid = claude_app_session_id(sid)
        if app_sid:
            try:
                subprocess.run(["open", f"claude://code/continue?session={app_sid}&source=agent_board"],
                               check=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                return False
            return True
    kind = "codex" if row["root"] == "codex" else "claude"
    target = (CONFIG.get("open_targets") or {}).get(kind, "folder")
    cwd = row.get("cwd")
    try:
        if target == "folder":
            if not cwd or not os.path.isdir(cwd):
                return False
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.run([opener, cwd], check=True, timeout=15)
        elif target == "vscode":
            user_data = (CONFIG.get("vscode_user_data_dirs") or {}).get(row["root"])
            url = (f"vscode://openai.chatgpt/local/{sid}" if kind == "codex" else
                   f"vscode://anthropic.claude-code/open?session={sid}")
            if sys.platform == "darwin" and not user_data:
                # The extension finds a session only from a window open on its folder, so focus that
                # window first. Launch Services avoids the CLI's extra helper window.
                if cwd and os.path.isdir(cwd):
                    subprocess.run(["open", "-a", "Visual Studio Code", cwd], check=True, timeout=15)
                    time.sleep(1.5)
                subprocess.run(["open", url], check=True, timeout=15)
            else:
                cli = (CONFIG.get("vscode_cli") or shutil.which("code") or
                       "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
                if not Path(cli).is_file():
                    return False
                base = [cli]
                if user_data:
                    base += ["--user-data-dir", str(Path(user_data).expanduser())]
                # --open-url treats every argument as a link, so focus the session's folder first;
                # the extension only finds a session from a window open on that folder.
                if cwd and os.path.isdir(cwd):
                    subprocess.run(base + [cwd], check=True, timeout=15)
                    time.sleep(1.5)
                subprocess.run(base + ["--open-url", url], check=True, timeout=15)
        else:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def resume_surface(row):
    """Name the app a session came from, so its resume chat opens there too."""
    if row["root"] == "codex":
        origin = row.get("originator") or ""
        if origin == "Codex Desktop":
            return "codex-app"
        return "codex-vscode" if "vscode" in origin else "codex-cli"
    entry = row.get("entrypoint") or ""
    if entry == "claude-vscode":
        return "claude-vscode"
    if entry == "cli":
        return "claude-cli"
    return "claude-app"


def resume_prompt(row):
    kind = "codex" if row["root"] == "codex" else "claude"
    snap = Path.home() / ".agent-handoffs" / f"{kind}-{row['id']}.md"
    return (f"Use the resume skill to pick up session {row['id']}. "
            f"Snapshot: {snap}")


def resume_in_new_chat(sid, hours):
    """Start a new chat in the session's own app with a resume prompt.

    Returns "sent" when the prompt was placed in the new chat, "copied" when
    the app has no prompt link and the prompt is on the clipboard, or None.
    """
    snapshot = _recent_status
    row = next((r for r in snapshot[2] if r["id"] == sid), None) if snapshot else None
    if row is None:
        row = next((r for r in status(hours)["sessions"] if r["id"] == sid), None)
    if not row or sys.platform != "darwin":
        return None
    prompt = resume_prompt(row)
    cwd = row.get("cwd") if row.get("cwd") and os.path.isdir(row["cwd"]) else None
    surface = resume_surface(row)
    try:
        if surface == "claude-app":
            url = "claude://code/new?source=agent_board&q=" + quote(prompt)
            if cwd:
                url += "&folder=" + quote(cwd)
            subprocess.run(["open", url], check=True, timeout=15)
        elif surface == "codex-app":
            url = "codex://new?prompt=" + quote(prompt)
            if cwd:
                url += "&path=" + quote(cwd)
            subprocess.run(["open", url], check=True, timeout=15)
        elif surface in ("claude-vscode", "codex-vscode"):
            if surface == "claude-vscode":
                url = "vscode://anthropic.claude-code/open?prompt=" + quote(prompt)
            else:
                # The Codex extension has no link that fills a new chat, so hand
                # the prompt over through the clipboard and bring Codex forward.
                url = "vscode://openai.chatgpt/"
                subprocess.run(["pbcopy"], input=prompt.encode(), check=True, timeout=15)
            user_data = (CONFIG.get("vscode_user_data_dirs") or {}).get(row["root"])
            # As in open_session, focus the session's folder window first so the
            # new chat starts in the right workspace.
            if not user_data:
                if cwd:
                    subprocess.run(["open", "-a", "Visual Studio Code", cwd], check=True, timeout=15)
                    time.sleep(1.5)
                subprocess.run(["open", url], check=True, timeout=15)
            else:
                cli = (CONFIG.get("vscode_cli") or shutil.which("code") or
                       "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
                if not Path(cli).is_file():
                    return None
                base = [cli, "--user-data-dir", str(Path(user_data).expanduser())]
                if cwd:
                    subprocess.run(base + [cwd], check=True, timeout=15)
                    time.sleep(1.5)
                subprocess.run(base + ["--open-url", url], check=True, timeout=15)
            if surface == "codex-vscode":
                return "copied"
        else:
            tool = "codex" if surface == "codex-cli" else "claude"
            cmd = (f"cd {shlex.quote(cwd)} && " if cwd else "") + f"{tool} {shlex.quote(prompt)}"
            script = cmd.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{script}"',
                            "-e", 'tell application "Terminal" to activate'], check=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return "sent"


FLAGS_FILE = DATA_DIR / "agent_board_flags.json"
COMPLETED_FILE = DATA_DIR / "agent_board_completed.json"
CHOICES_FILE = DATA_DIR / "agent_board_choices.json"
SUGGESTIONS_FILE = DATA_DIR / "agent_board_suggestions.json"
_completed_lock = threading.Lock()
_flags_lock = threading.Lock()


def load_flags():
    try:
        return json.loads(FLAGS_FILE.read_text())
    except Exception:
        return {}


def save_flag(sid, on, note=""):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        raise ValueError("invalid session id")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _flags_lock:
        flags = load_flags()
        if on:
            flags[sid] = {"note": note, "at": time.time()}
        else:
            flags.pop(sid, None)
        write_flags(flags)


def write_flags(flags):
    tmp = FLAGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(flags, indent=1))
    tmp.replace(FLAGS_FILE)


def save_workstream_flag(root, on, note=""):
    if not ws.valid_id(root):
        raise ValueError("invalid workstream id")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _flags_lock:
        flags = load_flags()
        links = ws.load()["links"]
        for sid in list(flags):
            if ws.valid_id(sid) and ws.root_for(sid, links) == root:
                flags.pop(sid)
        if on:
            flags[root] = {"note": note, "at": time.time()}
        write_flags(flags)


def load_completed():
    try:
        return json.loads(COMPLETED_FILE.read_text())
    except (OSError, ValueError):
        return {}


def load_choices():
    try:
        return json.loads(CHOICES_FILE.read_text())
    except (OSError, ValueError):
        return {}


def load_suggestions():
    try:
        return json.loads(SUGGESTIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_choice(sid, choice):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid) or choice not in ("continue", "temporary", "dismiss", "clear"):
        raise ValueError("invalid choice")
    with _completed_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        choices = load_choices()
        if choice == "clear":
            choices.pop(sid, None)
        else:
            choices[sid] = {"state": choice, "at": time.time()}
        tmp = CHOICES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(choices, indent=1))
        tmp.replace(CHOICES_FILE)


def save_completed(sid, on):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        raise ValueError("invalid session id")
    with _completed_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        completed = load_completed()
        if on:
            completed[sid] = {"at": time.time(), "source": "board"}
        else:
            # Remember an Undo until a new user instruction, so the board and
            # a late Stop hook cannot immediately re-apply the old closeout.
            completed[sid] = {"at": time.time(), "source": "board-undone"}
        tmp = COMPLETED_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(completed, indent=1))
        tmp.replace(COMPLETED_FILE)


def visible_suggestion(suggestion, now, activity):
    """Stop displaying stale review suggestions without changing saved decisions."""
    if not isinstance(suggestion, dict):
        return None
    if suggestion.get("state") in ("likely_done", "temporary"):
        since = suggestion.get("at")
        if not isinstance(since, (int, float)):
            since = activity
        if now - since >= SUGGESTION_REVIEW_HOURS * 3600:
            return None
    return suggestion


def board_bucket(row):
    """One display bucket shared by the web page and menu bar plugin."""
    if row["completed"]:
        # A chat "continue later" closes this session but keeps its starred
        # workstream in the saved follow-up list.
        if row.get("completion_source") == "chat-parked" and row.get("flag"):
            return "pending"
        return "completed"
    if row["choice"] == "temporary":
        return "temporary"
    state = row["state"]
    if state in ("asking", "check"):
        return state
    if state in ("working", "running"):
        return "active"
    suggestion = row.get("suggestion") or {}
    suggested_state = suggestion.get("state") if row["choice"] != "dismiss" else None
    if row["choice"] == "continue":
        return "pending"
    if row["flag"]:
        return "pending"
    # Automatic suggestions must not move a finished session out of review.
    if state == "yourturn":
        return "yourturn"
    if suggested_state in ("continue", "waiting"):
        return "pending"
    if suggested_state in ("likely_done", "temporary"):
        return "suggested"
    return state if state in ("yourturn", "idle") else "idle"


def park_requested(session, completed, now):
    """Apply an explicit chat closeout on the first status poll, before Stop."""
    user_at = session.get("last_user_ts")
    if (not user_at or not 0 <= now - user_at <= 120 or
            not turn_classifier.is_explicit_park(session.get("last_user"))):
        return False
    marker = completed.get(session["id"]) or {}
    if marker.get("source") == "chat-parked" and marker.get("at", 0) >= user_at:
        return False
    if marker.get("source") == "board-undone" and marker.get("at", 0) >= user_at:
        return False
    if not turn_classifier.save_parked(session["id"], at=now, user_at=user_at):
        return False
    completed[session["id"]] = {"at": now, "source": "chat-parked"}
    turn_classifier.clear_suggestion(session["id"])
    return True


def completion_active(row, marker):
    if not marker or marker.get("source") == "board-undone":
        return False
    if marker.get("source") == "chat-parked":
        # Assistant activity after the user's closeout should not reopen it.
        return bool(row.get("last_user_ts") and row["last_user_ts"] <= marker.get("at", 0))
    return row["activity"] <= marker.get("at", 0)


def recover_suggestion(session, path, now, completed):
    """Cover a missed Stop hook for a recently finished turn."""
    finished_at = session.get("last_ts")
    recently_visible = (now - finished_at <= YOUR_TURN_HOURS * 3600 or
                        now - path.stat().st_mtime <= YOUR_TURN_HOURS * 3600)
    if (session.get("last_kind") != "done" or not finished_at or
            not 10 <= now - finished_at <= 24 * 3600 or not recently_visible or
            not session.get("last_reply")):
        return None
    key = (session["id"], finished_at)
    if key not in _fallback_cache:
        state, reason = turn_classifier.classify({
            "last_assistant_message": session["last_reply"],
            "transcript_path": str(path),
        })
        if state in ("chat_done", "chat_parked"):
            if state == "chat_parked":
                if turn_classifier.save_parked(session["id"], at=now, user_at=session.get("last_user_ts")):
                    completed[session["id"]] = {"at": now, "source": "chat-parked"}
            else:
                turn_classifier.save_completion(session["id"], at=now)
                completed[session["id"]] = {"at": now, "source": "chat-closeout"}
            turn_classifier.clear_suggestion(session["id"])
            _fallback_cache[key] = None
        else:
            turn_classifier.save(session["id"], state, reason, source="board-fallback-rules")
            _fallback_cache[key] = {"state": state, "reason": reason, "at": now,
                                    "source": "board-fallback-rules"}
    return _fallback_cache[key]


def status(hours):
    global _recent_status
    now = time.time()
    ps_lines, n_claude = ps_snapshot()
    flags = load_flags()
    completed = load_completed()
    choices = load_choices()
    suggestions = load_suggestions()
    # v0.4.6-dev briefly allowed fallback closeouts to land as suggestions.
    # Promote those records once, preserving their original timestamp so a
    # later substantive user message still reopens the session.
    for sid, suggestion in list(suggestions.items()):
        if not isinstance(suggestion, dict) or suggestion.get("state") not in ("chat_done", "chat_parked"):
            continue
        at = suggestion.get("at")
        if not isinstance(at, (int, float)):
            at = now
        marker = completed.get(sid) or {}
        if marker.get("at", 0) < at:
            if suggestion["state"] == "chat_parked":
                if turn_classifier.save_parked(sid, at=at):
                    completed[sid] = {"at": at, "source": "chat-parked"}
                    flags = load_flags()
            else:
                turn_classifier.save_completion(sid, at=at)
                completed[sid] = {"at": at, "source": "chat-closeout"}
        turn_classifier.clear_suggestion(sid)
        suggestions.pop(sid, None)
    flags = load_flags()  # fallback recovery may have added a parked star
    lineage = ws.load()
    app_titles = claude_app_titles()
    linked_ids = set(lineage["links"]) | {v["parent"] for v in lineage["links"].values()}
    rows = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for p in root.glob("*/*.jsonl"):
            try:
                if now - p.stat().st_mtime > hours * 3600 and p.stem not in flags and p.stem not in linked_ids:
                    continue
                s = dict(parse_session(p))
                s["title"] = claude_display_title(p, s["title"], app_titles)
            except Exception:
                continue
            state, detail = classify(s, now, ps_lines)
            if park_requested(s, completed, now):
                flags = load_flags()
                suggestions.pop(s["id"], None)
            previous = suggestions.get(s["id"]) or {}
            if previous.get("at", 0) < (s.get("last_ts") or 0) - 5:
                recovered = recover_suggestion(s, p, now, completed)
                if recovered:
                    suggestions[s["id"]] = recovered
                else:
                    suggestions.pop(s["id"], None)
            if completed.get(s["id"], {}).get("source") == "chat-parked":
                flags = load_flags()  # a missed hook may have parked it during fallback
            rows.append({**{k: v for k, v in s.items() if k not in ("pending", "last_reply")}, "pending_list": s["pending"], "state": state, "detail": detail,
                         "quiet_min": round((now - s["activity"]) / 60, 1), "flag": flags.get(p.stem)})
    for p in (CODEX_DIR / "sessions").glob("*/*/*/*.jsonl"):
        try:
            s = parse_codex(p) if (now - p.stat().st_mtime <= hours * 3600 or p.stem[-36:] in flags or p.stem[-36:] in linked_ids) else None
        except Exception:
            continue
        if not s:
            continue
        state, detail = classify(s, now, ps_lines)
        if park_requested(s, completed, now):
            flags = load_flags()
            suggestions.pop(s["id"], None)
        previous = suggestions.get(s["id"]) or {}
        if previous.get("at", 0) < (s.get("last_ts") or 0) - 5:
            recovered = recover_suggestion(s, p, now, completed)
            if recovered:
                suggestions[s["id"]] = recovered
            else:
                suggestions.pop(s["id"], None)
        if completed.get(s["id"], {}).get("source") == "chat-parked":
            flags = load_flags()  # a missed hook may have parked it during fallback
        rows.append({**{k: v for k, v in s.items() if k not in ("pending", "last_reply")}, "pending_list": s["pending"], "state": state, "detail": detail,
                     "quiet_min": round((now - s["activity"]) / 60, 1), "flag": flags.get(s["id"])})
    tree = None
    for r in rows:
        marker = completed.get(r["id"])
        r["completed"] = completion_active(r, marker)
        r["completion_source"] = marker.get("source") if r["completed"] else None
        choice = choices.get(r["id"])
        r["choice"] = (choice.get("state") if choice and
                       (choice.get("state") == "continue" or r["activity"] <= choice.get("at", 0)) else None)
        suggestion = suggestions.get(r["id"])
        r["suggestion"] = visible_suggestion(suggestion, now, r["activity"])
        r["hint"] = hint(r["state"], r["detail"])
        r["progress"] = ""
        if r["state"] in ("check", "running"):
            if r["last_kind"] == "done":
                jobs = [j for j in live_bg(r, now, ps_lines) if j["name"] == "Bash"]
            else:
                jobs = sorted([p for p in r["pending_list"] if p["name"] == "Bash"], key=lambda p: -(p["ts"] or 0))[:1]
            if jobs:
                if tree is None:
                    tree = ps_tree()
                j = min(jobs, key=lambda x: x["ts"] or now)
                r["progress"] = job_progress(j["cmd"], tree)
        del r["pending_list"]
    rows = [r for r in rows if not r["title"].lower().startswith("classify this bpm breadcrumb")]
    inherit_resume_titles(rows, lineage["links"])
    rows.sort(key=lambda r: -r["activity"])
    for r in rows:
        r["bucket"] = board_bucket(r)
    workstreams = ws.make_workstreams(rows, lineage, flags)
    by_id = {r["id"]: r for r in rows}
    for group in workstreams:
        if group["completed"]:
            for sid in group["session_ids"]:
                by_id[sid]["underlying_bucket"] = by_id[sid]["bucket"]
                by_id[sid]["bucket"] = "completed"
    link_suggestions = ws.link_suggestions(rows, lineage)
    result = {"now": now, "version": BOARD_VERSION, "claude_processes": n_claude, "sessions": rows,
              "workstreams": workstreams, "link_suggestions": link_suggestions}
    _recent_status = (hours, time.monotonic(), rows)
    return result


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent Board</title><link rel="icon" href="/app-icon.png"><style>
:root{--canvas:#fff;--sidebar:#f7f7f5;--ink:#202127;--muted:#72757d;--line:#e9e9e7;--blue:#3c6fdb;--blue-soft:#edf3ff;--brand:linear-gradient(135deg,#2f6fde,#8b5cf6);--amber:#d99a12;--red:#df5258;--green:#259b63;--purple:#8561dc;--grey:#9399a4}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--canvas);color:var(--ink);font:13px/1.44 "Avenir Next",Avenir,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid #9bb8f3;outline-offset:2px}.app{min-height:100vh}.sidebar{position:fixed;inset:0 auto 0 0;width:218px;background:var(--sidebar);border-right:1px solid #e7e8e5;display:flex;flex-direction:column;padding:19px 11px 15px;z-index:30}.identity{display:flex;align-items:center;gap:10px;padding:0 10px 21px}.identity-mark{width:29px;height:29px;background:var(--brand);border-radius:8px;color:white;font-size:16px;font-weight:800;display:grid;place-items:center}.identity-name{font-size:15px;font-weight:750;letter-spacing:-.025em}.sidebar-label{font-size:10px;font-weight:750;color:#a0a4aa;letter-spacing:.075em;text-transform:uppercase;padding:18px 11px 7px}.nav{display:grid;gap:2px}.nav button{display:flex;align-items:center;gap:10px;text-align:left;width:100%;border:0;background:transparent;color:#555b65;border-radius:7px;padding:8px 10px;min-height:36px;font-size:12px;font-weight:600}.nav button:hover{background:#eeefec}.nav button.selected{background:#e9e9e6;color:#242831}.nav-icon{width:17px;height:17px;display:grid;place-items:center;flex:none}.nav-icon svg{width:16px;height:16px;stroke:currentColor;stroke-width:1.8;fill:none;stroke-linecap:round;stroke-linejoin:round}.nav .number{font-size:10px;color:#8a8e96;margin-left:auto}.sidebar-spacer{flex:1}.sidebar-note{border-top:1px solid #e4e5e2;padding:14px 10px 0;color:#858990;font-size:10px;line-height:1.5}.sidebar-note strong{color:#555e68;display:block;font-size:11px;margin-bottom:3px}
.main{margin-left:218px;min-width:0}.masthead{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.97);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}.toolbar{display:flex;align-items:center;gap:14px;min-height:58px;padding:0 clamp(20px,3vw,42px)}.crumb{color:#8d9199;font-size:11px}.crumb strong{color:#4a505b;font-weight:650}.toolbar-spacer{flex:1}.live{color:#828892;font-size:11px;white-space:nowrap}.live:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:6px}.search{position:relative;max-width:255px;width:100%}.search span{position:absolute;left:10px;top:7px;color:#9ca1aa}.search input{width:100%;height:33px;padding:6px 10px 6px 31px;border-radius:7px;border:1px solid #e3e5e9;background:#f8f9fa;color:var(--ink)}.search input::placeholder{color:#9a9ea6}.reset{border:1px solid #e2e5e9;background:white;color:#5a6574;border-radius:7px;font-size:11px;font-weight:650;padding:7px 10px}.reset:hover{background:#f7f8fa}
.status-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));padding:0 clamp(20px,3vw,42px) 12px;gap:0}.status-strip button{display:flex;align-items:center;gap:7px;min-width:0;text-align:left;border:0;border-right:1px solid #eceef1;background:transparent;padding:4px 12px 4px 0;margin-right:12px;color:#69717e}.status-strip button:last-child{border-right:0}.status-strip button:hover{color:#202127}.status-strip .status-dot{width:7px;height:7px;border-radius:50%;background:var(--tone);flex:none}.status-strip strong{font-size:16px;color:#29313e;font-weight:750;line-height:1}.status-strip span:last-child{font-size:10px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.status-strip .ask{--tone:var(--amber)}.status-strip .check{--tone:var(--red)}.status-strip .review{--tone:var(--blue)}.status-strip .work{--tone:var(--green)}.status-strip .later{--tone:var(--purple)}.status-strip .idle{--tone:var(--grey)}
.page{max-width:1550px;margin:auto;padding:30px clamp(20px,3vw,42px) 62px}.page-title{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:24px}.page-title h1{font-size:29px;line-height:1.14;letter-spacing:-.04em;font-weight:740;margin:0}.page-title p{color:#858a93;font-size:11px;margin:6px 0 0}.filters{display:flex;gap:3px;padding:3px;background:#f2f3f5;border-radius:8px}.filters button{border:0;border-radius:6px;background:transparent;color:#7b8089;font-size:11px;font-weight:650;padding:6px 10px}.filters button[aria-pressed=true]{background:white;color:#303944;box-shadow:0 1px 3px #17202e12}
.workspace-grid{display:grid;grid-template-columns:minmax(0,1.48fr) minmax(292px,.82fr);gap:28px;align-items:start}.lists{min-width:0}.list-section{border:1px solid #e8e9eb;border-radius:10px;margin-bottom:16px;overflow:hidden;background:white;scroll-margin-top:140px}.list-head{display:flex;align-items:center;gap:8px;min-height:46px;padding:0 15px;border-bottom:1px solid #eceef0}.list-head h2{font-size:13px;letter-spacing:-.012em;margin:0;font-weight:730}.list-head small{font-size:10px;color:#9297a0;margin-left:auto}.count{border-radius:99px;background:#f0f1f3;color:#6c7580;padding:1px 6px;font-size:10px;font-weight:700}.group-head{display:flex;align-items:center;gap:7px;font-size:10px;font-weight:750;color:#606a79;padding:11px 15px 6px}.group-head .dot{width:7px;height:7px;border-radius:50%;background:var(--tone)}.group-head.ask{--tone:var(--amber)}.group-head.check{--tone:var(--red)}.group-head.review{--tone:var(--blue)}.group-head.work{--tone:var(--green)}.group-head.later{--tone:var(--purple)}.group-head span:last-child{color:#a0a6ae;font-weight:500;margin-left:auto}.work-row{width:100%;display:grid;grid-template-columns:16px minmax(0,1fr) auto;align-items:center;gap:9px;text-align:left;border:0;border-top:1px solid #f0f1f2;background:#fff;padding:9px 15px;min-height:55px;color:inherit}.work-row:first-child{border-top:0}.work-row:hover{background:#f8fafd}.work-row.selected{background:#eff4ff}.work-row .row-marker{width:7px;height:7px;border-radius:50%;background:var(--tone);justify-self:center}.work-row.ask{--tone:var(--amber)}.work-row.check{--tone:var(--red)}.work-row.review{--tone:var(--blue)}.work-row.work{--tone:var(--green)}.work-row.later{--tone:var(--purple)}.work-row.idle{--tone:var(--grey)}.row-copy{min-width:0}.row-copy strong{font-size:12px;font-weight:700;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row-copy small{font-size:10px;color:#838b97;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}.row-end{font-size:10px;color:#949ba6;white-space:nowrap}.row-end .agent{margin-right:10px;color:#677386}.row-end .arrow{font-size:13px;margin-left:7px}.empty{padding:17px;color:#9299a4;font-size:11px}
.detail{position:sticky;top:151px;border:1px solid #e7e9ee;border-radius:10px;background:#fff;overflow:hidden;min-width:0}.detail-head{display:flex;align-items:center;justify-content:space-between;padding:13px 18px;border-bottom:1px solid #eceef2;font-size:11px;color:#7a8290}.detail-head strong{color:#495365;font-weight:700}.detail-body{padding:20px 20px 18px}.detail-status{display:flex;align-items:center;gap:7px;font-size:11px;font-weight:750;color:var(--tone)}.detail-status .dot{width:7px;height:7px;border-radius:50%;background:currentColor}.detail-title{font-size:21px;font-weight:740;letter-spacing:-.03em;line-height:1.25;margin:12px 0 8px}.detail-summary{color:#5f6876;font-size:12px;line-height:1.6;margin:0}.detail-meta{display:flex;gap:7px;align-items:center;color:#9097a0;font-size:10px;margin-top:11px}.detail-divider{border:0;border-top:1px solid #eceef1;margin:19px 0}.detail-label{font-size:10px;font-weight:740;color:#9aa0aa;text-transform:uppercase;letter-spacing:.065em;margin-bottom:7px}.detail-context{color:#596575;font-size:11px;line-height:1.55}.suggestion{background:#f0f4ff;border-left:2px solid var(--blue);padding:9px 11px;margin-top:16px;color:#45609a;font-size:11px;line-height:1.5}.suggestion strong{display:block;color:#315baf}.detail-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:19px}.action{border:1px solid #dfe5ee;background:#fff;color:#385887;border-radius:7px;min-height:32px;padding:6px 10px;font-size:11px;font-weight:700}.action:hover{background:#f4f7fc}.action.primary{background:var(--blue);border-color:var(--blue);color:#fff}.action.primary:hover{background:#2d59ba}.action.subtle{color:#637085}.detail-extra{display:grid;gap:5px;padding:14px 20px;background:#fafbfc;border-top:1px solid #eceef2;color:#8b929e;font-size:10px}.detail-extra span{display:flex;justify-content:space-between;gap:12px}.detail-extra b{color:#687487;font-weight:650}.demo-note{color:#a0a5ac;font-size:10px;margin-top:22px}
@media(max-width:1200px){.sidebar{width:190px}.main{margin-left:190px}.status-strip{grid-template-columns:repeat(3,minmax(0,1fr));row-gap:8px}.workspace-grid{gap:18px;grid-template-columns:minmax(0,1.35fr) minmax(270px,.85fr)}.page{padding-top:24px}.detail{top:179px}}
@media(max-width:850px){.sidebar{position:static;width:100%;height:auto;padding:10px 14px}.identity{padding:0}.nav,.sidebar-label,.sidebar-spacer,.sidebar-note{display:none}.main{margin-left:0}.workspace-grid{grid-template-columns:1fr}.detail{position:static}.status-strip{grid-template-columns:repeat(3,minmax(0,1fr))}.toolbar{padding:0 18px}.status-strip{padding-left:18px;padding-right:18px}.page{padding-left:18px;padding-right:18px}.live{display:none}}
@media(max-width:600px){.search{max-width:180px}.toolbar{gap:7px}.crumb,.reset{display:none}.page-title{display:block}.filters{width:max-content;margin-top:14px}.status-strip{grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.status-strip button{border:0;margin:0;padding:5px 0}.status-strip span:last-child{font-size:9px}.row-end .agent{display:none}.group-head span:last-child{display:none}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
/* Native UI typography keeps the dense workspace crisp at small sizes. */
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
.identity-name{font-weight:700}
.page-title h1{font-size:27px;font-weight:700;letter-spacing:-.035em}
.list-head h2{font-weight:650}
.group-head{font-weight:650}
.row-copy strong{font-weight:600}
.detail-head strong{font-weight:650}
.detail-title{font-size:20px;font-weight:680}
.detail-status,.detail-label{font-weight:650}
.action{font-weight:650}
.group-head.idle{--tone:var(--grey)}.group-head.done{--tone:var(--green)}.group-head.temporary{--tone:var(--purple)}.work-row.done{--tone:var(--green)}.work-row.temporary{--tone:var(--purple)}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:50;background:#243247;color:white;border-radius:7px;padding:9px 13px;font-size:11px;box-shadow:0 8px 24px #15203428}.toast[hidden]{display:none}

/* Production controls and longer real session content. */
.view-switch{display:flex;gap:3px;padding:3px;background:#f2f3f5;border-radius:8px}
.view-switch button{border:0;background:transparent;border-radius:6px;padding:6px 9px;color:#69717e;font-size:11px;font-weight:650;white-space:nowrap}
.view-switch button[aria-pressed=true]{background:#fff;color:#303944;box-shadow:0 1px 3px #17202e12}
.live.offline:before{background:var(--red)}
.session-list{display:grid;gap:7px;margin-top:10px;max-height:260px;overflow:auto}
.session-line{display:flex;align-items:center;gap:6px;border-top:1px solid #eff0f2;padding-top:7px;font-size:11px;color:#647080}
.session-line span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.linkitem{display:flex;align-items:center;gap:8px;padding:8px 15px;border-top:1px solid #eff0f2;font-size:11px}.linkitem .pair{flex:1;min-width:0}.linkitem small{display:block;color:#8b929e}
.linkresults{display:grid;gap:6px;max-height:40vh;overflow:auto}.linkresults button{text-align:left}
details.replies summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:8px;min-height:46px;padding:0 15px;font-size:13px;font-weight:650}details.replies summary::-webkit-details-marker{display:none}details.replies summary:after{content:'›';margin-left:auto;color:#9aa0aa;font-size:18px}details.replies[open] summary:after{transform:rotate(90deg)}details.replies .session-line{padding:8px 15px}
dialog{border:1px solid #e7e9ee;border-radius:10px;padding:20px;max-width:min(540px,90vw);width:100%;box-shadow:0 15px 45px #2021272c}dialog::backdrop{background:#20212766}
#link-section[hidden]{display:none}
.detail{max-height:calc(100vh - 165px);overflow:auto}.detail-summary,.detail-context{overflow-wrap:anywhere}
.work-row .row-copy small{max-width:100%}
@media(max-width:850px){.detail{max-height:none}.toolbar{flex-wrap:wrap;padding-top:9px;padding-bottom:9px}}
@media(max-width:600px){.view-switch{order:3}.toolbar .search{order:4;max-width:none}.toolbar .live{display:none}}
/* Review build: compact empty sections, collapsed navigation and clear controls. */
.sidebar{width:64px;padding:16px 8px}.main{margin-left:64px}.sidebar .identity{display:grid;justify-items:center;gap:8px;padding:0 0 18px}.identity-mark{width:34px;height:34px;background:none;box-shadow:none;overflow:hidden}.identity-mark img{width:100%;height:100%;object-fit:contain}.identity-name,.sidebar-label,.sidebar-note,.nav-label{display:none}.sidebar .nav button{position:relative;justify-content:center;padding:8px;min-height:40px}.sidebar .nav .number{position:absolute;right:0;top:0;margin:0;background:#e9ecf2;border-radius:99px;min-width:13px;text-align:center;font-size:9px}.sidebar .nav .number:empty{display:none}.sidebar-spacer{min-height:8px}.nav-toggle{display:grid;place-items:center;width:26px;height:24px;border:0;border-radius:6px;background:transparent;color:#7a8290;font-size:18px}.nav-toggle:hover{background:#e9e9e6}
.app.nav-expanded .sidebar{width:218px;padding:19px 11px 15px}.app.nav-expanded .main{margin-left:218px}.app.nav-expanded .sidebar .identity{display:flex;justify-items:initial;padding:0 10px 21px}.app.nav-expanded .identity-name,.app.nav-expanded .sidebar-label,.app.nav-expanded .sidebar-note,.app.nav-expanded .nav-label{display:block}.app.nav-expanded .nav-toggle{margin-left:auto;flex:none}.app.nav-expanded .sidebar .nav button{justify-content:flex-start;padding:8px 10px;min-height:36px}.app.nav-expanded .sidebar .nav .number{position:static;margin-left:auto;background:none;font-size:10px}
details.list-section>summary.list-head{list-style:none;cursor:pointer}details.list-section>summary.list-head::-webkit-details-marker{display:none}details.list-section>summary.list-head:after{content:'›';color:#a0a6ae;font-size:18px;margin-left:8px}details.list-section[open]>summary.list-head:after{transform:rotate(90deg)}details.list-section>summary.list-head small{margin-left:auto}.group-head[hidden],.list-section [hidden]{display:none!important}
.toolbar .release-button{border:1px solid #e2e5e9;background:#fff;color:#53617a;border-radius:7px;font-size:11px;font-weight:650;padding:7px 10px;white-space:nowrap}.toolbar .release-button:hover{background:#f6f8fb}.release-copy{font-size:12px;line-height:1.6;color:#596575}.release-copy strong{color:#303944}.release-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}.release-actions a{text-decoration:none}.release-actions a.primary{background:var(--blue);border-color:var(--blue);color:#fff}
.detail-actions .action.star{font-size:19px;line-height:1;padding:4px 10px;min-width:34px;color:#8a68d8}.detail-actions .action.star.is-on{color:#e0a100}.action-tooltip{position:fixed;z-index:1000;box-sizing:border-box;width:max-content;max-width:min(260px,calc(100vw - 24px));background:#263242;color:#fff;border-radius:6px;padding:7px 9px;font-size:11px;font-weight:500;line-height:1.4;white-space:normal;box-shadow:0 7px 20px #26324233;pointer-events:none}.action-tooltip[hidden]{display:none}
@media(max-width:850px){.sidebar,.app.nav-expanded .sidebar{width:100%;position:static;height:auto;padding:8px 14px}.main,.app.nav-expanded .main{margin-left:0}.sidebar .identity,.app.nav-expanded .sidebar .identity{display:flex;justify-content:flex-start;gap:9px;padding:0}.identity-name{display:block}.sidebar .nav,.sidebar .sidebar-label,.sidebar .sidebar-spacer,.sidebar .sidebar-note{display:none!important}.nav-toggle{margin-left:auto}.toolbar .release-button{display:inline-flex}}
@media(max-width:600px){.toolbar .release-button{order:5}.toolbar .search{order:4}}
</style><link rel="stylesheet" href="/custom.css"></head><body>
<div class="app" id="app"><aside class="sidebar" id="sidebar"><div class="identity"><span class="identity-mark"><img src="/app-icon.png" alt="Agent Board icon"></span><span class="identity-name">Agent Board</span><button class="nav-toggle" id="nav-toggle" type="button" aria-label="Expand sidebar" aria-expanded="false" aria-controls="sidebar" title="Expand sidebar">›</button></div>
<div class="nav"><button class="selected" type="button" data-nav="overview" aria-label="Overview" title="Overview"><span class="nav-icon"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></span><span class="nav-label">Overview</span></button><button type="button" data-nav="attention" aria-label="Needs attention" title="Needs attention"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M4 4h16v12H4z"/><path d="M4 16l4 4h8l4-4"/></svg></span><span class="nav-label">Needs attention</span><span class="number" id="nav-attention">0</span></button><button type="button" data-nav="working" aria-label="Working" title="Working"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span><span class="nav-label">Working</span><span class="number" id="nav-working">0</span></button><button type="button" data-nav="later" aria-label="Continue later" title="Continue later"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M5 4h14v17l-7-4-7 4z"/></svg></span><span class="nav-label">Continue later</span><span class="number" id="nav-later">0</span></button></div>
<div class="sidebar-label">Archive</div><div class="nav"><button type="button" data-nav="archive" aria-label="Other work" title="Other work"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M4 4h16v4H4zM6 8v12h12V8M10 12h4"/></svg></span><span class="nav-label">Other work</span><span class="number" id="nav-archive">0</span></button></div><div class="sidebar-spacer"></div><div class="sidebar-note">Local session board<br>Choices remain under your control.</div></aside>
<div class="main" id="overview"><div class="masthead"><div class="toolbar"><span class="crumb">Workspace &nbsp;/&nbsp; <strong>Overview</strong></span><div class="view-switch" aria-label="View"><button id="view-workstreams" data-view="workstreams" type="button" aria-pressed="true">Workstreams</button><button id="view-sessions" data-view="sessions" type="button" aria-pressed="false">Sessions</button></div><span class="toolbar-spacer"></span><span class="live" id="updated">Connecting…</span><label class="search"><span aria-hidden="true">⌕</span><input id="search" type="search" placeholder="Search current view" aria-label="Search current view"></label><button class="release-button" id="releases" type="button" title="See version and published releases">Releases ↗</button></div><div class="status-strip" aria-label="Board status counts"><button class="ask" type="button" data-jump="attention"><span class="status-dot"></span><strong id="metric-ask">0</strong><span>Asking you</span></button><button class="check" type="button" data-jump="attention"><span class="status-dot"></span><strong id="metric-check">0</strong><span>Check me</span></button><button class="review" type="button" data-jump="attention"><span class="status-dot"></span><strong id="metric-review">0</strong><span>Your turn</span></button><button class="work" type="button" data-jump="working"><span class="status-dot"></span><strong id="metric-work">0</strong><span>Working</span></button><button class="later" type="button" data-jump="later"><span class="status-dot"></span><strong id="metric-later">0</strong><span>Continue later</span></button><button class="idle" type="button" data-jump="archive"><span class="status-dot"></span><strong id="metric-idle">0</strong><span>Idle</span></button></div></div>
<main class="page"><div class="page-title"><div><h1>Overview</h1><p>Workstreams across Claude and Codex · select a row to review details</p></div><div class="filters" aria-label="Agent filter"><button type="button" data-agent="all" aria-pressed="true">All</button><button type="button" data-agent="claude" aria-pressed="false">Claude</button><button type="button" data-agent="codex" aria-pressed="false">Codex</button></div></div>
<div class="workspace-grid"><div class="lists"><details class="list-section" id="attention"><summary class="list-head"><h2>Needs your attention</h2><span class="count" id="count-attention">0</span><small>Review and decide the next step</small></summary><div class="section-content"><div class="group-head ask" data-group="asking"><span class="dot"></span>Asking you <span class="count" id="count-ask">0</span><span>Question or permission</span></div><div id="list-ask"></div><div class="group-head check" data-group="check"><span class="dot"></span>Check me <span class="count" id="count-check">0</span><span>May need intervention</span></div><div id="list-check"></div><div class="group-head review" data-group="yourturn"><span class="dot"></span>Your turn <span class="count" id="count-review">0</span><span>Agent replied</span></div><div id="list-review"></div></div></details>
<details class="list-section" id="working"><summary class="list-head"><h2>Working</h2><span class="count" id="count-work">0</span><small>Active sessions</small></summary><div class="section-content"><div id="list-work"></div></div></details>
<details class="list-section" id="later"><summary class="list-head"><h2>Continue later</h2><span class="count" id="count-later">0</span><small>Saved for later</small></summary><div class="section-content"><div id="list-later"></div></div></details>
<details class="list-section" id="archive"><summary class="list-head"><h2>Other work</h2><span class="count" id="count-archive">0</span><small>Manual states stay distinct</small></summary><div class="section-content"><div class="group-head later" data-group="suggested"><span class="dot"></span>Suggestions to review <span class="count" id="count-suggested">0</span><span>Advisory</span></div><div id="list-suggested"></div><div class="group-head idle" data-group="idle"><span class="dot"></span>Idle <span class="count" id="count-idle">0</span><span>No recent activity</span></div><div id="list-idle"></div><div class="group-head done" data-group="completed"><span class="dot"></span>Completed <span class="count" id="count-done">0</span><span>Confirmed by you</span></div><div id="list-done"></div><div class="group-head temporary" data-group="temporary"><span class="dot"></span>Temporary <span class="count" id="count-temporary">0</span><span>Manual state</span></div><div id="list-temporary"></div></div></details>
<details class="list-section replies" id="today"><summary>Agent replies today <span class="count" id="count-today">0</span></summary><div id="today-list"></div></details><section class="list-section" id="link-section" hidden><div class="list-head"><h2>Suggested session links</h2><span class="count" id="count-links">0</span><small>Confirm or dismiss</small></div><div id="link-list"></div></section></div>
<aside class="detail" id="detail" aria-live="polite"><div class="detail-head"><strong>Details</strong><span>Live data</span></div><div id="detail-content"></div></aside></div></main></div></div>
<dialog id="link-dialog"><strong>Link session to a workstream</strong><p>Choose the earlier workstream this session continues.</p><input id="link-search" type="search" placeholder="Search workstreams" style="width:100%;padding:9px;border:1px solid #d7dbe3;border-radius:8px"><div class="linkresults" id="link-results"></div><button class="action" id="link-cancel" type="button">Cancel</button></dialog>
<dialog id="releases-dialog"><h2 style="margin:0 0 12px;font-size:19px">Agent Board releases</h2><div class="release-copy"><p>Running service: <strong id="release-service-version">Checking…</strong></p><p>Published releases and ready-built Mac downloads are available on the public GitHub project. No corporate VPN is required.</p></div><div class="release-actions"><a class="action primary" href="https://github.com/stellassx94/agent-board/releases">Open published releases ↗</a><button class="action" id="releases-close" type="button">Close</button></div></dialog>
<script>const LABEL={asking:'Asking you',check:'Check me',yourturn:'Your turn',active:'Working',pending:'Continue later',idle:'Idle',completed:'Completed',temporary:'Temporary',suggested:'Suggestions to review'};
const TONE={asking:'ask',check:'check',yourturn:'review',active:'work',pending:'later',idle:'idle',completed:'done',temporary:'temporary',suggested:'later'};
const SUGGEST={continue:'Continue later',waiting:'Waiting for you',likely_done:'Likely done',temporary:'Temporary',uncertain:'Uncertain'};
let data=null,account='all',view='workstreams',query='',selected=null;
let navExpanded=false;
try{account=localStorage.getItem('acct')||'all';view=localStorage.getItem('view')||'workstreams';if(!['all','claude','codex'].includes(account))account='all';if(!['workstreams','sessions'].includes(view))view='workstreams'}catch(e){}
try{navExpanded=localStorage.getItem('navExpanded')==='true'}catch(e){}
const $=s=>document.querySelector(s);
const nativeUpdater=window.webkit?.messageHandlers?.agentBoardUpdates;
if(nativeUpdater){const b=$('#releases');b.textContent='Check for updates…';b.title='Check the latest published release'}
function updateNav(){const toggle=$('#nav-toggle');$('#app').classList.toggle('nav-expanded',navExpanded);toggle.setAttribute('aria-expanded',String(navExpanded));toggle.setAttribute('aria-label',navExpanded?'Collapse sidebar':'Expand sidebar');toggle.title=navExpanded?'Collapse sidebar':'Expand sidebar';toggle.textContent=navExpanded?'‹':'›'}
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const plain=s=>String(s??'').replace(/\*\*|`/g,'').replace(/\[([^\]]+)\]\([^)]*\)/g,'$1');
const ago=m=>m<1?'just now':m<60?`${Math.round(m)} min ago`:m<1440?`${(m/60).toFixed(1)} h ago`:`${Math.round(m/1440)} d ago`;
const accountName=r=>r==='codex'?'Codex':'Claude';
const rootNames=w=>[...new Set(w.roots.map(accountName))].join(' + ');
const lead=w=>data.sessions.find(s=>s.id===w.lead_id);
const latest=w=>data.sessions.find(s=>s.id===w.latest_id);
const byId=id=>(view==='workstreams'?data.workstreams:data.sessions).find(x=>x.id===id);
const titleOf=x=>x.title||'Untitled session';
const detailOf=x=>x.detail||'';
const activityOf=x=>view==='workstreams'?ago((data.now-x.activity)/60):ago(x.quiet_min);
const bucketOf=x=>x.bucket;
const rootsOf=x=>view==='workstreams'?rootNames(x):accountName(x.root);
const visible=x=>(account==='all'||(view==='workstreams'?x.roots.some(r=>(r==='codex'?'codex':'claude')===account):(x.root==='codex'?'codex':'claude')===account))&&(!query||`${x.title} ${x.detail} ${x.project||''} ${rootsOf(x)}`.toLowerCase().includes(query));
function renderToday(){const today=new Date().toDateString();const xs=data.sessions.filter(s=>(account==='all'||(s.root==='codex'?'codex':'claude')===account)&&['yourturn','idle'].includes(s.state)&&s.last_kind==='done'&&s.last_ts&&new Date(s.last_ts*1000).toDateString()===today).sort((a,b)=>b.last_ts-a.last_ts);count('count-today',xs.length);$('#today-list').innerHTML=xs.length?xs.map(s=>`<div class="session-line"><span>${escapeHTML(s.title)} · ${escapeHTML(accountName(s.root))} · ${new Date(s.last_ts*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><button type="button" class="action" data-action="open" data-id="${escapeHTML(s.id)}">Open ↗</button></div>`).join(''):'<div class="empty">No agent replies yet today.</div>'}
const count=(id,n)=>{const el=$('#'+id);if(el){el.textContent=n;if(el.classList.contains('number'))el.hidden=n===0}};
function row(x){const b=bucketOf(x),tone=TONE[b]||'idle';return `<button type="button" class="work-row ${tone}${selected===x.id?' selected':''}" data-select="${escapeHTML(x.id)}" aria-pressed="${selected===x.id}"><span class="row-marker"></span><span class="row-copy"><strong>${escapeHTML(titleOf(x))}</strong><small>${escapeHTML(detailOf(x))}</small></span><span class="row-end"><span class="agent">${escapeHTML(rootsOf(x))}</span>${escapeHTML(activityOf(x))}<span class="arrow">›</span></span></button>`}
function suggestion(s){if(!s?.suggestion||s.choice==='dismiss')return '';return `<div class="suggestion"><strong>Suggested: ${escapeHTML(SUGGEST[s.suggestion.state]||'Uncertain')}</strong>${escapeHTML(s.suggestion.reason)}<br>Review the session before choosing a state.</div>`}
function action(cls,id,label,extra=''){
 const help={open:'Open the latest linked session.',resumenew:'Start a new chat in the same app and run the resume skill for this session.',groupfinish:'Confirm this workstream is complete. Only you can mark it done.',finish:'Manually mark this session done.',continue:label.startsWith('Undo')?'Remove this saved follow-up.':'Save this work for follow-up. It remains open until you change its state.',temporary:label.startsWith('Undo')?'Move this work out of Temporary.':'Move this work out of active lists. It returns if the session resumes.',dismiss:'Hide this advisory suggestion. The work stays open.',star:label==='Remove star'?'Remove the star and its follow-up note.':'Star this workstream for Continue later and optionally add a note.',link:'Link this session to an earlier workstream.',unlink:'Remove the confirmed session link.',accept:'Confirm this suggested session link.',reject:'Dismiss this suggested link without changing the sessions.'};
 const description=help[cls]||label,display=cls==='star'?(label==='Remove star'?'★':'☆'):label,on=cls==='star'&&label==='Remove star';
 return `<button type="button" class="action ${cls}${on?' is-on':''}" data-action="${cls}" data-id="${escapeHTML(id)}" aria-label="${escapeHTML(label)}" data-tooltip="${escapeHTML(description)}" ${extra}>${display}</button>`
}
const actionTooltip=document.createElement('div');
actionTooltip.id='action-tooltip';actionTooltip.className='action-tooltip';actionTooltip.role='tooltip';actionTooltip.hidden=true;document.body.append(actionTooltip);
let tooltipTarget=null;
function hideActionTooltip(){if(tooltipTarget)tooltipTarget.removeAttribute('aria-describedby');tooltipTarget=null;actionTooltip.hidden=true}
function showActionTooltip(target){
 if(!target?.dataset.tooltip)return;
 if(tooltipTarget!==target)hideActionTooltip();
 tooltipTarget=target;actionTooltip.textContent=target.dataset.tooltip;actionTooltip.hidden=false;target.setAttribute('aria-describedby',actionTooltip.id);
 const anchor=target.getBoundingClientRect(),tip=actionTooltip.getBoundingClientRect(),margin=12;
 const left=Math.max(margin,Math.min(anchor.left+anchor.width/2-tip.width/2,window.innerWidth-tip.width-margin));
 let top=anchor.top-tip.height-9;
 if(top<margin)top=anchor.bottom+9;
 actionTooltip.style.left=`${left}px`;actionTooltip.style.top=`${Math.max(margin,Math.min(top,window.innerHeight-tip.height-margin))}px`;
}
document.addEventListener('pointerover',e=>{const target=e.target.closest?.('[data-tooltip]');if(target)showActionTooltip(target)});
document.addEventListener('pointerout',e=>{if(tooltipTarget&&!tooltipTarget.contains(e.relatedTarget))hideActionTooltip()});
document.addEventListener('focusin',e=>{const target=e.target.closest?.('[data-tooltip]');if(target)showActionTooltip(target)});
document.addEventListener('focusout',e=>{if(tooltipTarget&&!tooltipTarget.contains(e.relatedTarget))hideActionTooltip()});
document.addEventListener('scroll',hideActionTooltip,true);window.addEventListener('resize',hideActionTooltip);
function foldSection(id,n){const section=$('#'+id);if(section.dataset.count!==String(n)){section.open=n>0;section.dataset.count=String(n)}}
function detail(x){if(!x)return '<div class="empty">Select a workstream to see its details.</div>';const b=bucketOf(x),isGroup=view==='workstreams',l=isGroup?lead(x):x,last=isGroup?latest(x):x,n=isGroup?x.session_count:1;
 const status=b==='yourturn'&&x.needs_completion?'Your turn':LABEL[b]||'Idle';
 const context=b==='asking'?'The agent is asking a question or permission. Open the latest session to respond.':b==='check'?'The session may need intervention. Open it to verify what is happening.':b==='yourturn'?'The agent replied. Review the result and decide the next step.':b==='idle'?'There is no recent activity. Idle does not mean complete.':detailOf(x);
 const completionConfirmed=x.completed||(isGroup&&l?.completed),completionSource=x.completed?x.completion_source:l?.completion_source,completionText=!completionConfirmed?'Not confirmed':completionSource==='chat-parked'?'Session done · starred for later':completionSource==='chat-closeout'?'Confirmed from chat':'Confirmed by you';
 return `<div class="detail-body"><div class="detail-status" style="--tone:var(--${{asking:'amber',check:'red',yourturn:'blue',active:'green',pending:'purple',idle:'grey',completed:'green',temporary:'purple',suggested:'purple'}[b]||'grey'});color:var(--tone)"><span class="dot"></span>${escapeHTML(status)}</div><h2 class="detail-title">${escapeHTML(titleOf(x))}</h2><p class="detail-summary">${escapeHTML(detailOf(x))}</p><div class="detail-meta"><span>${escapeHTML(rootsOf(x))}</span><span>·</span><span>${n} ${n===1?'session':'sessions'}</span><span>·</span><span>${escapeHTML(activityOf(x))}</span></div>${suggestion(l)}${x.flag_note?`<div class="suggestion">Note: ${escapeHTML(x.flag_note)}</div>`:''}<hr class="detail-divider"><div class="detail-label">What is happening</div><div class="detail-context">${escapeHTML(context)}</div><div class="detail-actions">${action('open',last?.id||x.id,'Open latest ↗')}${action('resumenew',last?.id||x.id,'Resume in new chat ↻')}${isGroup?(x.completed||!['active','completed'].includes(b)?action('groupfinish',x.id,x.completed?'Undo workstream done':'Workstream done',`data-on="${x.completed?'0':'1'}"`):''):action('finish',x.id,x.completed?'Undo done':'Session done',`data-on="${x.completed?'0':'1'}"`)}${l?action('continue',l.id,l.choice==='continue'?'Undo Continue later':'Continue later'):''}${l?action('temporary',l.id,l.choice==='temporary'?'Undo Temporary':'Temporary'):''}${l?.suggestion?action('dismiss',l.id,l.choice==='dismiss'?'Restore suggestion':'Dismiss suggestion'):''}${action('star',x.id,x.flag?'Remove star':'Star',`data-scope="${isGroup?'workstream':'session'}" data-on="${x.flag?'0':'1'}"`)}</div>${isGroup?`<div class="detail-label" style="margin-top:20px">Linked sessions</div><div class="session-list">${x.session_ids.slice().reverse().map(id=>{const s=data.sessions.find(z=>z.id===id);return s?`<div class="session-line"><span>${escapeHTML(s.title)}</span>${action('open',s.id,'Open ↗')}${action('resumenew',s.id,'Resume new ↻')}${s.linked_from?action('unlink',s.id,'Unlink'):''}</div>`:''}).join('')}</div>`:action('link',x.id,x.linked_from?'Unlink session':'Link to workstream')}</div><div class="detail-extra"><span><b>Latest activity</b>${escapeHTML(activityOf(x))}</span><span><b>Completion</b>${completionText}</span></div>`}
function render(){if(!data)return;hideActionTooltip();const items=(view==='workstreams'?data.workstreams:data.sessions).filter(visible),groups=Object.fromEntries(Object.keys(LABEL).map(k=>[k,items.filter(x=>x.bucket===k)]));
 if(!items.some(x=>x.id===selected))selected=items.find(x=>['asking','check','yourturn'].includes(x.bucket))?.id||items[0]?.id||null;
 for(const [bucket,id] of Object.entries({asking:'ask',check:'check',yourturn:'review',active:'work',pending:'later',idle:'idle',completed:'done',temporary:'temporary',suggested:'suggested'})){const xs=groups[bucket],list=$('#list-'+id),head=document.querySelector(`[data-group="${bucket}"]`);list.innerHTML=xs.map(row).join('');list.hidden=xs.length===0;if(head)head.hidden=xs.length===0;count('count-'+id,xs.length);count('metric-'+id,xs.length)}
 const attention=groups.asking.length+groups.check.length+groups.yourturn.length,archive=groups.idle.length+groups.completed.length+groups.temporary.length+groups.suggested.length;
 count('count-attention',attention);count('count-archive',archive);count('nav-attention',attention);count('nav-working',groups.active.length);count('nav-later',groups.pending.length);count('nav-archive',archive);
 foldSection('attention',attention);foldSection('working',groups.active.length);foldSection('later',groups.pending.length);foldSection('archive',archive);
 $('#detail-content').innerHTML=detail(items.find(x=>x.id===selected));renderToday();$('#view-workstreams').setAttribute('aria-pressed',String(view==='workstreams'));$('#view-sessions').setAttribute('aria-pressed',String(view==='sessions'));
 document.querySelectorAll('[data-agent]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.agent===account)));
 $('#view-workstreams').textContent=`Workstreams (${data.workstreams.length})`;$('#view-sessions').textContent=`Sessions (${data.sessions.length})`;
 const links=data.link_suggestions.filter(x=>account==='all'||(data.sessions.find(s=>s.id===x.child)?.root==='codex'?'codex':'claude')===account);$('#link-section').hidden=view!=='workstreams'||!links.length;count('count-links',links.length);
 $('#link-list').innerHTML=links.map(x=>`<div class="linkitem"><div class="pair"><b>${escapeHTML(x.child_title)}</b> → ${escapeHTML(x.parent_title)}<small>${escapeHTML(x.reason)}</small></div>${action('accept',x.child,'Link',`data-parent="${escapeHTML(x.parent)}"`)}${action('reject',x.child,'Dismiss',`data-parent="${escapeHTML(x.parent)}"`)}</div>`).join('');
 $('#updated').textContent=`Live · updated ${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} · ${data.version||'local copy'}`;$('#updated').classList.remove('offline');document.title=`Agent Board · ${attention} need attention`;
 $('#release-service-version').textContent=data.version||'local copy';
}
let tickBusy=false;
async function tick(){if(tickBusy)return;tickBusy=true;try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('Offline');data=await r.json();render()}catch(e){$('#updated').textContent='Board service offline';$('#updated').classList.add('offline');document.title='Agent Board offline'}finally{tickBusy=false}}
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Could not save change');await tick()}
let linkChild=null;
function linkResults(){const q=$('#link-search').value.toLowerCase().trim(),current=data.sessions.find(s=>s.id===linkChild)?.workstream_id;$('#link-results').innerHTML=data.workstreams.filter(w=>w.id!==linkChild&&w.id!==current&&(!q||w.title.toLowerCase().includes(q))).slice(0,30).map(w=>`<button type="button" class="action" data-action="linktarget" data-id="${escapeHTML(w.id)}">${escapeHTML(w.title)} · ${w.session_count} sessions</button>`).join('')||'<div class="empty">No matching workstreams</div>'}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;
 if(b.id==='nav-toggle'){navExpanded=!navExpanded;try{localStorage.setItem('navExpanded',String(navExpanded))}catch(e){}updateNav();return}
 if(b.id==='releases'){if(nativeUpdater){nativeUpdater.postMessage('check')}else{$('#release-service-version').textContent=data?.version||'offline';$('#releases-dialog').showModal()}return}
 if(b.id==='releases-close'){$('#releases-dialog').close();return}
 if(b.dataset.select){selected=b.dataset.select;render();return}if(b.dataset.agent){account=b.dataset.agent;try{localStorage.setItem('acct',account)}catch(e){}render();return}if(b.dataset.view){view=b.dataset.view;selected=null;try{localStorage.setItem('view',view)}catch(e){}render();return}
 if(b.dataset.nav){document.querySelectorAll('[data-nav]').forEach(x=>x.classList.toggle('selected',x===b));const section=document.getElementById(b.dataset.nav);if(section?.tagName==='DETAILS')section.open=true;section?.scrollIntoView({behavior:'smooth'});return}if(b.dataset.jump){const section=document.getElementById(b.dataset.jump);if(section?.tagName==='DETAILS')section.open=true;section?.scrollIntoView({behavior:'smooth'});return}
 const a=b.dataset.action;if(!a)return;const id=b.dataset.id;try{
 if(a==='resumenew'){const original=b.textContent;b.textContent='Starting…';const r=await fetch('/api/resume-new?id='+encodeURIComponent(id),{method:'POST'});const j=r.ok?await r.json():{};b.textContent=j.mode==='copied'?'Copied — paste in new Codex chat':r.ok?'New chat ready ✓ press Enter':'Could not start';setTimeout(()=>b.textContent=original,4000);return}
 if(a==='open'){const original=b.textContent;b.textContent='Opening…';const r=await fetch('/api/open?id='+encodeURIComponent(id),{method:'POST'});b.textContent=r.ok?'Opened ✓':'Could not open';setTimeout(()=>b.textContent=original,2500);return}
 if(a==='groupfinish')await post('/api/group-complete',{id,on:b.dataset.on==='1'});
 else if(a==='finish')await post('/api/complete',{id,on:b.dataset.on==='1'});
 else if(['continue','temporary','dismiss'].includes(a)){const s=data.sessions.find(x=>x.id===id);await post('/api/choice',{id,choice:s.choice===a?'clear':a})}
 else if(a==='star'){const on=b.dataset.on==='1';let note='';if(on){note=prompt('Note for later (optional):','');if(note===null)return}await post('/api/flag',{id,scope:b.dataset.scope,on,note})}
 else if(a==='accept'||a==='linktarget'){await post('/api/link',{child:a==='linktarget'?linkChild:id,parent:a==='linktarget'?id:b.dataset.parent});$('#link-dialog').close()}
 else if(a==='reject')await post('/api/link-reject',{child:id,parent:b.dataset.parent});
 else if(a==='unlink')await post('/api/unlink',{child:id});
 else if(a==='link'){const s=data.sessions.find(x=>x.id===id);if(s.linked_from)await post('/api/unlink',{child:id});else{linkChild=id;$('#link-search').value='';linkResults();$('#link-dialog').showModal()}}
 }catch(err){alert(err.message)}});
$('#search').addEventListener('input',e=>{query=e.target.value.trim().toLowerCase();render()});$('#link-search').addEventListener('input',linkResults);$('#link-cancel').addEventListener('click',()=>$('#link-dialog').close());
updateNav();tick();setInterval(tick,2000);
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    hours = 168

    def local_request(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin not in {f"http://{h}" for h in allowed}):
            self.send_error(403)
            return False
        return True

    def do_POST(self):
        if not self.local_request():
            return
        if self.path.startswith("/api/resume-new"):
            m = re.search(r"[?&]id=([0-9a-fA-F-]{36})", self.path)
            mode = resume_in_new_chat(m.group(1), self.hours) if m else None
            body = json.dumps({"mode": mode}).encode()
            self.send_response(200 if mode else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/open"):
            m = re.search(r"[?&]id=([0-9a-fA-F-]{36})", self.path)
            ok = bool(m) and open_session(m.group(1), self.hours)
            self.send_response(204 if ok else 404)
            self.end_headers()
            return
        if not self.path.startswith(("/api/flag", "/api/complete", "/api/choice", "/api/link", "/api/unlink", "/api/link-reject", "/api/group-complete")):
            self.send_error(404)
            return
        try:
            if int(self.headers.get("Content-Length", 0)) > 8192:
                raise ValueError("request too large")
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path.startswith("/api/complete"):
                save_completed(str(d["id"]), bool(d.get("on")))
            elif self.path.startswith("/api/choice"):
                save_choice(str(d["id"]), str(d["choice"]))
            elif self.path.startswith("/api/group-complete"):
                ws.complete(str(d["id"]), bool(d.get("on")))
            elif self.path.startswith("/api/link-reject"):
                ws.reject(str(d["child"]), str(d["parent"]))
            elif self.path.startswith("/api/unlink"):
                ws.unlink(str(d["child"]))
            elif self.path.startswith("/api/link"):
                ws.link(str(d["child"]), str(d["parent"]), "manual")
            else:
                if d.get("scope") == "workstream":
                    save_workstream_flag(str(d["id"]), bool(d.get("on")), str(d.get("note", ""))[:300])
                else:
                    save_flag(str(d["id"]), bool(d.get("on")), str(d.get("note", ""))[:300])
        except Exception:
            self.send_error(400)
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if not self.local_request():
            return
        if self.path.startswith("/api/status"):
            body = json.dumps(status(self.hours)).encode()
            ctype = "application/json"
        elif self.path == "/custom.css":
            try:
                body = (DATA_DIR / "custom.css").read_bytes()
            except OSError:
                body = b""
            ctype = "text/css; charset=utf-8"
        elif self.path == "/app-icon.png":
            candidates = (Path(__file__).with_name("AgentBoardIcon.png"),
                          Path(__file__).parent / "macos" / "AgentBoardIcon.png")
            icon = next((p for p in candidates if p.is_file()), None)
            if icon is None:
                self.send_error(404)
                return
            body, ctype = icon.read_bytes(), "image/png"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--hours", type=float, default=168, help="show sessions active in the last N hours (marked ones always show)")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--once", action="store_true", help="print status as JSON and exit")
    a = ap.parse_args()
    if a.once:
        print(json.dumps(status(a.hours), indent=1))
        return
    Handler.hours = a.hours
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Agent Board running at {url}  (Ctrl+C to stop)")
    if not a.no_open:
        webbrowser.open(url)
    srv.serve_forever()


if __name__ == "__main__":
    main()
