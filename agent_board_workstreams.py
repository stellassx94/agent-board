#!/usr/bin/python3
"""Agent Board workstream lineage, review decisions, and resume capture."""

import fcntl
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
MARKER_RE = re.compile(r"agent_board_workstreams\.py\s+resume-source\s+['\"]?((?:claude|codex)-)?([0-9a-fA-F-]{36})")
DATA_DIR = Path(os.environ.get("AGENT_BOARD_DATA_DIR", "~/.agent-board")).expanduser()
DATA_FILE = Path(os.environ.get("AGENT_BOARD_LINEAGE_FILE", str(DATA_DIR / "agent_board_lineage.json"))).expanduser()
NOISE = {"resume", "session", "chat", "the", "this", "from", "where", "left", "off", "that", "claude", "codex", "continue", "continuing", "work", "and", "for", "agent", "board", "repo", "prd", "code"}
PRIORITY = {"asking": 0, "check": 1, "active": 2, "pending": 3, "yourturn": 5,
            "suggested": 6, "idle": 7, "temporary": 8, "completed": 9}


def valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value))


def load():
    try:
        value = json.loads(DATA_FILE.read_text())
    except (OSError, ValueError):
        value = {}
    return {"links": value.get("links", {}), "rejected": value.get("rejected", {}),
            "completed": value.get("completed", {})}


def mutate(fn):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE.with_suffix(".lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load()
        result = fn(data)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(DATA_FILE)
        fcntl.flock(lock, fcntl.LOCK_UN)
        return result


def root_for(sid, links):
    seen = set()
    while sid in links:
        if sid in seen:
            raise ValueError("lineage cycle")
        seen.add(sid)
        sid = links[sid]["parent"]
    return sid


def link(child, parent, source="manual"):
    if not valid_id(child) or not valid_id(parent) or child == parent:
        raise ValueError("invalid session link")
    def change(data):
        links = data["links"]
        cursor, seen = parent, set()
        while cursor in links:
            if cursor == child or cursor in seen:
                raise ValueError("lineage cycle")
            seen.add(cursor)
            cursor = links[cursor]["parent"]
        if cursor == child:
            raise ValueError("lineage cycle")
        links[child] = {"parent": parent, "source": source, "at": time.time()}
        data["rejected"].pop(child + ":" + parent, None)
    mutate(change)


def unlink(child):
    if not valid_id(child):
        raise ValueError("invalid session id")
    mutate(lambda data: data["links"].pop(child, None))


def reject(child, parent):
    if not valid_id(child) or not valid_id(parent):
        raise ValueError("invalid session ids")
    mutate(lambda data: data["rejected"].update({child + ":" + parent: time.time()}))


def complete(root, on):
    if not valid_id(root):
        raise ValueError("invalid workstream id")
    def change(data):
        if on:
            data["completed"][root] = {"at": time.time()}
        else:
            data["completed"].pop(root, None)
    mutate(change)


def tokens(title):
    value = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    return {part for part in value.split() if (len(part) > 1 or part.isdigit()) and part not in NOISE}


def link_suggestions(rows, data, limit=20):
    """Suggest older same-folder resume targets; never commit these links."""
    links, rejected = data["links"], data["rejected"]
    out = []
    for child in rows:
        if child["id"] in links or "resume" not in child["title"].lower():
            continue
        ct = tokens(child["title"])
        if len(ct) < 2:
            continue
        candidates = []
        for parent in rows:
            if parent["id"] == child["id"] or parent["activity"] >= child["activity"]:
                continue
            if child.get("cwd") != parent.get("cwd") or not child.get("cwd"):
                continue
            if child["id"] + ":" + parent["id"] in rejected:
                continue
            if root_for(parent["id"], links) == child["id"]:
                continue
            pt = tokens(parent["title"])
            shared = ct & pt
            if len(shared) < 2:
                continue
            coverage = len(shared) / len(ct)
            if coverage < .65:
                continue
            score = coverage + (0.2 if "resume" not in parent["title"].lower() else 0)
            candidates.append((score, parent["activity"], parent))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = candidates[0][2]
        out.append({"child": child["id"], "parent": best["id"], "child_title": child["title"],
                    "parent_title": best["title"], "reason": "Similar topic in the same folder; review before linking."})
    return out[:limit]


def make_workstreams(rows, data, flags=None):
    links = data["links"]
    flags = flags or {}
    by_id = {r["id"]: r for r in rows}
    grouped = defaultdict(list)
    for r in rows:
        root = root_for(r["id"], links)
        r["workstream_id"] = root
        r["linked_from"] = links.get(r["id"], {}).get("parent")
        grouped[root].append(r)
    result = []
    for root, members in grouped.items():
        members.sort(key=lambda r: -r["activity"])
        parent_ids = {links[r["id"]]["parent"] for r in members if r["id"] in links}
        leaves = [r for r in members if r["id"] not in parent_ids] or members[:1]
        lead = min(leaves, key=lambda r: (PRIORITY.get(r["bucket"], 99), -r["activity"]))
        # A resumed leaf must retain the star from any earlier member or root.
        marked = flags.get(root) or next((r.get("flag") for r in members if r.get("flag")), None)
        newest = members[0]
        manual = data["completed"].get(root)
        done = bool(manual and newest["activity"] <= manual.get("at", 0))
        needs_completion = len(members) > 1 and all(r["bucket"] == "completed" for r in leaves)
        if done or (len(members) == 1 and leaves[0]["bucket"] == "completed"):
            bucket = "completed"
        elif needs_completion:
            bucket = "suggested"
        elif all(r["bucket"] == "temporary" for r in leaves):
            bucket = "temporary"
        elif marked and lead["bucket"] not in ("asking", "check", "active"):
            bucket = "pending"
        else:
            bucket = lead["bucket"]
        original = by_id.get(root)
        title = (original or next((r for r in reversed(members) if "resume" not in r["title"].lower()), newest))["title"]
        result.append({"id": root, "title": title, "bucket": bucket, "activity": newest["activity"],
                       "session_ids": [r["id"] for r in members], "session_count": len(members),
                       "lead_id": lead["id"], "latest_id": newest["id"], "detail": lead["detail"],
                       "flag_id": root, "flag": marked, "flagged": bool(marked),
                       "flag_note": (marked or {}).get("note", ""),
                       "roots": sorted({r["root"] for r in members}), "completed": done,
                       "needs_completion": needs_completion,
                       "linked_count": sum(r["id"] in links for r in members)})
    result.sort(key=lambda w: -w["activity"])
    return result


def capture_source(transcript_path):
    """Read only actual tool commands, never ordinary prose or tool output."""
    if not transcript_path or not Path(transcript_path).is_file():
        return None
    commands = []
    with open(transcript_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        first = f.read(min(size, 2_000_000)).splitlines()
        if size > 2_000_000:
            first = first[:-1]
            f.seek(max(0, size - 2_000_000))
            tail = f.read().splitlines()[1:]
            lines = first + tail
        else:
            lines = first
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get("type") == "assistant":
            for block in (row.get("message") or {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                    commands.append((block.get("input") or {}).get("command", ""))
        elif row.get("type") == "response_item":
            payload = row.get("payload") or {}
            if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
                source = payload.get("input") or ""
                if "tools.exec_command" in source:
                    commands.append(source)
            elif payload.get("type") == "function_call" and payload.get("name") in ("exec_command", "shell"):
                try:
                    args = json.loads(payload.get("arguments") or "{}")
                except ValueError:
                    args = {}
                commands.append(args.get("cmd", ""))
    matches = {m.group(2) for command in commands if isinstance(command, str) for m in MARKER_RE.finditer(command)}
    return next(iter(matches)) if len(matches) == 1 else None


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "resume-source" and len(sys.argv) == 3:
        raw = sys.argv[2]
        # Split on the source prefix only; UUIDs themselves contain hyphens.
        sid = raw[7:] if raw.startswith("claude-") else raw[6:] if raw.startswith("codex-") else raw
        if not valid_id(sid):
            raise SystemExit("Invalid source session ID")
        print("Agent Board resume source noted: " + sid)
        return
    if command == "capture-stop":
        try:
            hook = json.load(sys.stdin)
            child = str(hook.get("session_id") or "")
            parent = capture_source(hook.get("transcript_path"))
            if valid_id(child) and parent and child != parent:
                link(child, parent, "resume")
        except Exception:
            pass
        print("{}")
        return
    raise SystemExit("Usage: agent_board_workstreams.py resume-source ID | capture-stop")


if __name__ == "__main__":
    main()
