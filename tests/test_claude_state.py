import importlib
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
board = importlib.import_module("agent_board")


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def user(content, at, **extra):
    return {
        "type": "user",
        "timestamp": stamp(at),
        "cwd": "/tmp/project",
        "message": {"role": "user", "content": content},
        **extra,
    }


def assistant(content, at, stop_reason=None, **extra):
    return {
        "type": "assistant",
        "timestamp": stamp(at),
        "cwd": "/tmp/project",
        "message": {"role": "assistant", "content": content, "stop_reason": stop_reason},
        **extra,
    }


class ClaudeStateTests(unittest.TestCase):
    def setUp(self):
        board._cache.clear()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / ".claude" / "projects" / "project"
        root.mkdir(parents=True)
        self.path = root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows, mtime=None):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        if mtime is not None:
            os.utime(self.path, (mtime, mtime))

    def append(self, row, mtime=None):
        with self.path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        if mtime is not None:
            os.utime(self.path, (mtime, mtime))

    def test_genuine_user_turn_is_working(self):
        now = 2_000_000_000
        self.write([user("Please investigate", now - 5)], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("thinking", parsed["last_kind"])
        self.assertEqual(("working", "Thinking / writing."), board.classify(parsed, now, []))

    def test_active_tool_call_is_running(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "/tmp/a"}}
        self.write([user("Read this", now - 20), assistant([call], now - 10, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("tool", parsed["last_kind"])
        self.assertEqual("running", board.classify(parsed, now, [])[0])

    def test_unstarted_bash_without_permission_marker_stays_running(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Bash",
                "input": {"command": "python3 build_release.py", "description": "Build release"}}
        self.write([user("Build it", now - 30), assistant([call], now - 20, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("running", board.classify(parsed, now, [])[0])

    def test_permission_marker_with_pending_tool_enters_asking(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Bash",
                "input": {"command": "python3 build_release.py", "description": "Build release"}}
        self.write([user("Build it", now - 30), assistant([call], now - 20, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        state, detail = board.classify(parsed, now, [], {"at": now - 19})
        self.assertEqual("asking", state)
        self.assertIn("permission", detail)

    def test_older_permission_marker_is_ignored(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Bash",
                "input": {"command": "python3 build_release.py", "description": "Build release"}}
        self.write([user("Build it", now - 30), assistant([call], now - 20, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("running", board.classify(parsed, now, [], {"at": now - 60})[0])

    def test_newer_tool_result_clears_permission_marker(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Edit", "input": {"file_path": "/tmp/a"}}
        call2 = {"type": "tool_use", "id": "tool-2", "name": "Read", "input": {"file_path": "/tmp/b"}}
        result = [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]
        self.write([user("Edit it", now - 30), assistant([call], now - 20, "tool_use"),
                    user(result, now - 10), assistant([call2], now - 9, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertNotEqual("asking", board.classify(parsed, now, [], {"at": now - 19})[0])

    def test_live_bash_process_clears_permission_marker(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Bash",
                "input": {"command": "python3 build_release.py", "description": "Build release"}}
        self.write([user("Build it", now - 30), assistant([call], now - 20, "tool_use")], mtime=now)
        parsed = board.parse_session(self.path)
        prompt = {"at": now - 19}
        self.assertEqual("running", board.classify(parsed, now, ["python3 build_release.py"], prompt)[0])

    def test_permission_marker_without_pending_tool_is_ignored(self):
        now = 2_000_000_000
        self.write([user("Hi", now - 30), assistant([{"type": "text", "text": "Hello"}], now - 20, "end_turn")], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("yourturn", board.classify(parsed, now, [], {"at": now - 5})[0])

    def test_subagent_activity_clears_permission_marker(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Agent",
                "input": {"description": "Search", "prompt": "Find it"}}
        self.write([user("Find it", now - 60), assistant([call], now - 50, "tool_use")], mtime=now - 50)
        sub = self.path.with_suffix("") / "subagents"
        sub.mkdir(parents=True)
        log = sub / "agent-1.jsonl"
        log.write_text("{}\n")
        os.utime(log, (now - 40, now - 40))
        parsed = board.parse_session(self.path)
        prompt = {"at": now - 39}
        self.assertEqual("asking", board.classify(parsed, now, [], prompt)[0])
        os.utime(log, (now - 5, now - 5))
        parsed = board.parse_session(self.path)
        self.assertNotEqual("asking", board.classify(parsed, now, [], prompt)[0])

    def test_tool_result_keeps_real_turn_active(self):
        now = 2_000_000_000
        call = {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "/tmp/a"}}
        result = [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]
        self.write([
            user("Read this", now - 20),
            assistant([call], now - 15, "tool_use"),
            user(result, now - 5),
        ], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("thinking", parsed["last_kind"])
        self.assertEqual("working", board.classify(parsed, now, [])[0])

    def test_task_notification_does_not_reopen_finished_turn(self):
        now = 2_000_000_000
        finished = now - 600
        notification = "<task-notification><tool-use-id>tool-bg</tool-use-id><status>stopped</status></task-notification>"
        self.write([
            user("Do the work", finished - 30),
            assistant([{"type": "text", "text": "Done"}], finished, "end_turn"),
            user(notification, now - 5, origin={"kind": "task-notification"}, promptSource="system"),
            {"type": "cost-state", "timestamp": stamp(now - 1)},
        ], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("done", parsed["last_kind"])
        self.assertEqual(finished, parsed["activity"])
        self.assertEqual("yourturn", board.classify(parsed, now, [])[0])

    def test_metadata_write_does_not_refresh_activity_or_cache(self):
        now = 2_000_000_000
        finished = now - 600
        self.write([
            user("Do the work", finished - 30),
            assistant([{"type": "text", "text": "Done"}], finished, "end_turn"),
        ], mtime=finished)
        first = board.parse_session(self.path)
        self.append({"type": "bridge-session", "timestamp": stamp(now)}, mtime=now)
        second = board.parse_session(self.path)
        self.assertEqual(finished, first["activity"])
        self.assertEqual(finished, second["activity"])
        self.assertEqual("done", second["last_kind"])

    def test_rate_limit_message_finishes_instead_of_fake_working(self):
        now = 2_000_000_000
        self.write([
            user("Continue", now - 30),
            assistant(
                [{"type": "text", "text": "You've hit your monthly spend limit"}],
                now - 5,
                "stop_sequence",
                isApiErrorMessage=True,
                error="rate_limit",
            ),
        ], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("done", parsed["last_kind"])
        self.assertEqual("yourturn", board.classify(parsed, now, [])[0])

    def test_background_notification_clears_job_without_changing_done_state(self):
        now = 2_000_000_000
        call = {
            "type": "tool_use",
            "id": "tool-bg",
            "name": "Bash",
            "input": {"command": "long-specific-command-123", "run_in_background": True},
        }
        notification = "<task-notification><tool-use-id>tool-bg</tool-use-id><status>completed</status></task-notification>"
        self.write([
            user("Run it", now - 30),
            assistant([call], now - 25, "tool_use"),
            user([{"type": "tool_result", "tool_use_id": "tool-bg", "content": "launched in background"}], now - 20),
            assistant([{"type": "text", "text": "Started"}], now - 15, "end_turn"),
            user(notification, now - 5, origin={"kind": "task-notification"}, promptSource="system"),
        ], mtime=now)
        parsed = board.parse_session(self.path)
        self.assertEqual("done", parsed["last_kind"])
        self.assertEqual([], parsed["bg"])

    def test_vscode_open_focuses_session_folder_before_link(self):
        sid = "33333333-3333-4333-8333-333333333333"
        with tempfile.TemporaryDirectory() as cwd:
            row = {"id": sid, "root": "~/.claude/projects", "cwd": cwd}
            calls = []
            with unittest.mock.patch.object(board, "_recent_status", (0, 0, [row])), \
                    unittest.mock.patch.object(board, "CONFIG", {"open_targets": {"claude": "vscode"}}), \
                    unittest.mock.patch.object(board, "claude_app_session_id", return_value=None), \
                    unittest.mock.patch.object(board.sys, "platform", "darwin"), \
                    unittest.mock.patch.object(board.time, "sleep"), \
                    unittest.mock.patch.object(board.subprocess, "run", side_effect=lambda a, **k: calls.append(a)):
                self.assertTrue(board.open_session(sid, 1))
        self.assertEqual([["open", "-a", "Visual Studio Code", cwd],
                          ["open", f"vscode://anthropic.claude-code/open?session={sid}"]], calls)


if __name__ == "__main__":
    unittest.main()
