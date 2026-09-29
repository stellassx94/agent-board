#!/usr/bin/python3
# <swiftbar.title>Agent Board</swiftbar.title>
# <swiftbar.desc>Workstream counts from the local Agent Board</swiftbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
import json
import os
import urllib.request
from pathlib import Path

URL = os.environ.get("AGENT_BOARD_URL", "http://127.0.0.1:8765/").rstrip("/") + "/"
BOARD = str(Path(__file__).resolve().parent.parent / "agent_board.py")


def clean(s, n=60):
    s = " ".join(str(s or "").replace("|", "/").split())
    return s if len(s) <= n else s[: n - 1] + "…"


try:
    d = json.load(urllib.request.urlopen(URL + "api/status", timeout=12))
except Exception:
    try:
        with urllib.request.urlopen(URL, timeout=2) as response:
            board_running = response.status == 200
    except Exception:
        board_running = False
    print("🟡 board slow" if board_running else "⚪ board off")
    print("---")
    if board_running:
        print("Agent Board is running, but its status request timed out. Refresh to retry.")
        print("Open Agent Board | bash=/usr/bin/open param1=-b param2=com.stella.agentboard.trial terminal=false")
        print(f"Open in browser | href={URL}")
    else:
        print("Agent Board server is not responding")
        print(f"Start board | bash=/bin/sh param1=-c param2='nohup /usr/bin/python3 \"{BOARD}\" --no-open >/dev/null 2>&1 &' terminal=false refresh=true")
    raise SystemExit

groups = {k: [] for k in ("asking", "check", "active", "pending", "yourturn", "suggested")}
for s in d.get("workstreams", d["sessions"]):
    bucket = s.get("bucket")
    if bucket in groups:
        groups[bucket].append(s)

c, a, y = len(groups["check"]), len(groups["active"]), len(groups["yourturn"])
q = len(groups["asking"])
p = len(groups["pending"])
title = " ".join(f"{icon}{count}" for icon, count in (("🟡", q), ("🔵", a), ("🟢", y), ("🔴", c), ("🟣", p)) if count) or "⚪"
print(title + " | font=Menlo size=12")
print("---")
print("Open Agent Board | bash=/usr/bin/open param1=-b param2=com.stella.agentboard.trial terminal=false")
print(f"Open in browser | href={URL}")
print("---")

SECTIONS = [("asking", "🟡 Asking you"), ("check", "🔴 Check me"), ("active", "🔵 Working"),
            ("yourturn", "🟢 Your turn"), ("pending", "🟣 Continue later"),
            ("suggested", "Suggestions to review")]
for k, name in SECTIONS:
    rows = groups[k]
    if not rows:
        continue
    print(f"{name} ({len(rows)}) | color=gray size=12")
    for s in rows[:12]:
        roots = s.get("roots") or [s.get("root")]
        acct = "+".join({".claude-work": "WORK", "codex": "CODEX"}.get(root, "MAIN") for root in roots)
        marker = "★ " if s.get("flagged", bool(s.get("flag"))) else ""
        print(f"{marker}{clean(s['title'])} | bash=/usr/bin/curl param1=-s param2=-X param3=POST "
              f"param4={URL}api/open?id={s.get('latest_id', s['id'])} terminal=false size=13")
        count = s.get("session_count", 1)
        print(f"--{acct} · {count} session{'s' if count != 1 else ''} · click title to open latest | size=12")
        print(f"--{clean(s['detail'], 90)} | size=12")
    if len(rows) > 12:
        print(f"…and {len(rows) - 12} more | href={URL} color=gray")
    print("---")

print("Refresh | refresh=true")
