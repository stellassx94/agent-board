import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

classifier = importlib.import_module("agent_board_classify")
board = importlib.import_module("agent_board")
workstreams = importlib.import_module("agent_board_workstreams")
SID = "01a0e10d-32d8-7fe2-af33-d8420e1ed107"


class ContinueLaterCloseoutTests(unittest.TestCase):
    def test_only_explicit_short_phrases_park(self):
        for value in ("continue later", "Continue later.", "let's continue later", "pause this and continue later"):
            with self.subTest(value=value):
                self.assertTrue(classifier.is_explicit_park(value))
        for value in ("can we continue later?", "don't continue later", "continue later, but first fix this", "I said continue later yesterday"):
            with self.subTest(value=value):
                self.assertFalse(classifier.is_explicit_park(value))

    def test_stop_hook_marks_done_and_stars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "session.jsonl"
            transcript.write_text(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "continue later"}}) + "\n")
            completed, flags, suggestions = (root / name for name in ("completed.json", "flags.json", "suggestions.json"))
            hook = {"session_id": SID, "transcript_path": str(transcript), "last_assistant_message": "Paused here."}
            with mock.patch.object(classifier, "COMPLETED_OUT", completed), mock.patch.object(classifier, "FLAGS_OUT", flags), mock.patch.object(classifier, "OUT", suggestions), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), mock.patch.object(sys, "argv", ["agent_board_classify.py"]), mock.patch("builtins.print"):
                classifier.main()
            marker = json.loads(completed.read_text())[SID]
            flag = json.loads(flags.read_text())[SID]
            self.assertEqual("chat-parked", marker["source"])
            self.assertEqual("", flag["note"])
            self.assertEqual({}, json.loads(suggestions.read_text()))

    def test_parked_session_is_done_and_in_later_list(self):
        row = {"id": SID, "title": "KB router study", "root": "codex", "activity": 100,
               "completed": True, "completion_source": "chat-parked", "choice": None,
               "state": "yourturn", "flag": {"note": "", "at": 101}, "detail": "Paused"}
        self.assertEqual("pending", board.board_bucket(row))
        row["bucket"] = "pending"
        groups = workstreams.make_workstreams([row], {"links": {}, "rejected": {}, "completed": {}}, {SID: row["flag"]})
        self.assertEqual("pending", groups[0]["bucket"])
        self.assertTrue(row["completed"])
        row["flag"] = None
        self.assertEqual("completed", board.board_bucket(row))
        row["completed"] = False  # later activity invalidates the timestamp-bound completion
        self.assertEqual("yourturn", board.board_bucket(row))


if __name__ == "__main__":
    unittest.main()
