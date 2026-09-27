import importlib
import json
import os
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
