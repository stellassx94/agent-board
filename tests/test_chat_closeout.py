import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


classifier = importlib.import_module("agent_board_classify")


class ChatCloseoutTests(unittest.TestCase):
    def test_capture_prompt_records_only_permission_prompts(self):
        sid = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "prompts.json"
            with mock.patch.object(classifier, "PROMPTS_OUT", out):
                self.assertFalse(classifier.save_prompt({"session_id": sid, "notification_type": "idle_prompt",
                                                         "message": "Claude is waiting for your input"}))
                self.assertFalse(classifier.save_prompt({"session_id": "bad", "notification_type": "permission_prompt"}))
                self.assertFalse(out.exists())
                self.assertTrue(classifier.save_prompt({"session_id": sid, "notification_type": "permission_prompt",
                                                        "message": "Claude needs your permission to use Bash"}))
                saved = json.loads(out.read_text())
                self.assertEqual(["message", "at"], sorted(saved[sid], reverse=True))
                with mock.patch.object(sys, "stdin", io.StringIO("not json")):
                    classifier.capture_prompt()

    def test_accepts_short_explicit_closeouts(self):
        accepted = ["done", "ok done", "Okay, done!", "all done",
                    "this session is done", "mark this session done",
                    "close the task", "thank you, done"]
        for value in accepted:
            with self.subTest(value=value):
                self.assertTrue(classifier.is_explicit_closeout(value))

    def test_rejects_questions_negations_and_followups(self):
        rejected = ["are we done?", "not done", "not done yet",
                    "done with step one, now do step two",
                    "ok done, but please update the README",
                    "the task is almost done", "I said done yesterday"]
        for value in rejected:
            with self.subTest(value=value):
                self.assertFalse(classifier.is_explicit_closeout(value))

    def test_classify_promotes_explicit_closeout(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "session.jsonl"
            transcript.write_text(json.dumps({
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "ok done"},
            }) + "\n")
            state, reason = classifier.classify({
                "transcript_path": str(transcript),
                "last_assistant_message": "Great — the repository is ready.",
            })
        self.assertEqual("chat_done", state)
        self.assertIn("explicitly", reason)

    def test_completion_marker_is_reversible_and_timestamp_bound(self):
        sid = "01a0e10d-32d8-7fe2-af33-d8420e1ed107"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "completed.json"
            with mock.patch.object(classifier, "COMPLETED_OUT", path), mock.patch.object(
                classifier.time, "time", return_value=1234.5
            ):
                classifier.save_completion(sid)
            marker = json.loads(path.read_text())[sid]
        self.assertEqual({"at": 1234.5, "source": "chat-closeout"}, marker)

    def test_stop_hook_writes_completion_instead_of_suggestion(self):
        sid = "01a0e10d-32d8-7fe2-af33-d8420e1ed107"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "session.jsonl"
            transcript.write_text(json.dumps({
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "ok done"},
            }) + "\n")
            completed = root / "completed.json"
            suggestions = root / "suggestions.json"
            hook = {
                "session_id": sid,
                "transcript_path": str(transcript),
                "last_assistant_message": "Understood.",
            }
            with mock.patch.object(classifier, "COMPLETED_OUT", completed), mock.patch.object(
                classifier, "OUT", suggestions
            ), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), mock.patch.object(
                sys, "argv", ["agent_board_classify.py"]
            ), mock.patch("builtins.print"):
                classifier.main()
            marker = json.loads(completed.read_text())[sid]
        self.assertEqual("chat-closeout", marker["source"])
        self.assertFalse(suggestions.exists())

    def test_clear_suggestion_removes_only_promoted_session(self):
        sid = "01a0e10d-32d8-7fe2-af33-d8420e1ed107"
        other = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suggestions.json"
            path.write_text(json.dumps({sid: {"state": "chat_done"},
                                        other: {"state": "continue"}}))
            with mock.patch.object(classifier, "OUT", path):
                classifier.clear_suggestion(sid)
            saved = json.loads(path.read_text())
        self.assertNotIn(sid, saved)
        self.assertEqual("continue", saved[other]["state"])


if __name__ == "__main__":
    unittest.main()
