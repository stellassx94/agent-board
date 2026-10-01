import importlib
import io
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
import unittest
from pathlib import Path
from unittest import mock

classifier = importlib.import_module("agent_board_classify")
board = importlib.import_module("agent_board")
workstreams = importlib.import_module("agent_board_workstreams")
SID = "01a0e10d-32d8-7fe2-af33-d8420e1ed107"


class ContinueLaterCloseoutTests(unittest.TestCase):
    def test_in_flight_codex_closeout_parks_before_stop_and_stays_put(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / (SID + ".jsonl")
            now = time.time()
            user_stamp = datetime.fromtimestamp(now - 2, timezone.utc).isoformat()
            reply_stamp = datetime.fromtimestamp(now - 1, timezone.utc).isoformat()
            transcript.write_text("\n".join(json.dumps(row) for row in (
                {"type": "session_meta", "payload": {"id": SID, "cwd": directory}},
                {"timestamp": user_stamp, "type": "event_msg", "payload": {"type": "user_message", "message": "continue later"}},
                {"timestamp": reply_stamp, "type": "event_msg", "payload": {"type": "agent_message", "message": "Parking this now."}},
            )) + "\n")
            completed_file, flags_file, suggestions_file = (root / name for name in ("completed.json", "flags.json", "suggestions.json"))
            with mock.patch.object(board, "codex_titles", return_value={}), mock.patch.object(classifier, "COMPLETED_OUT", completed_file), mock.patch.object(classifier, "FLAGS_OUT", flags_file), mock.patch.object(classifier, "OUT", suggestions_file), mock.patch.object(board, "COMPLETED_FILE", completed_file), mock.patch.object(board, "DATA_DIR", root):
                session = board.parse_codex(transcript)
                self.assertNotEqual("done", session["last_kind"])
                self.assertEqual("continue later", session["last_user"])
                completed = {}
                self.assertTrue(board.park_requested(session, completed, now))
                self.assertTrue(board.completion_active(session, completed[SID]))
                self.assertEqual("chat-parked", json.loads(completed_file.read_text())[SID]["source"])
                self.assertIn(SID, json.loads(flags_file.read_text()))
                in_flight = {"completed": True, "completion_source": "chat-parked", "flag": {"at": now}, "choice": None, "state": "running"}
                self.assertEqual("pending", board.board_bucket(in_flight))
                self.assertFalse(board.park_requested(session, completed, now + 2))
                flags_file.write_text("{}")  # a manual unstar must survive the late Stop hook
                self.assertFalse(classifier.save_parked(SID, at=now + 2, user_at=session["last_user_ts"]))
                self.assertEqual({}, json.loads(flags_file.read_text()))
                board.save_completed(SID, False)
                completed = board.load_completed()
                self.assertFalse(board.park_requested(session, completed, now + 3))
                self.assertFalse(classifier.save_parked(SID, at=now + 4, user_at=session["last_user_ts"]))
                later = dict(session, last_user="new task", last_user_ts=now + 5)
                self.assertFalse(board.completion_active(later, completed[SID]))

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


    def test_inherited_star_does_not_hide_fresh_reply(self):
        root = "11111111-1111-4111-8111-111111111111"
        leaf = "22222222-2222-4222-8222-222222222222"
        flag = {"note": "", "at": 50}
        rows = [{"id": root, "title": "Old chat", "root": "claude", "activity": 60, "bucket": "pending",
                 "flag": flag, "detail": "Idle."},
                {"id": leaf, "title": "Old chat", "root": "claude", "activity": 100, "bucket": "yourturn",
                 "flag": None, "detail": "Finished. Waiting for you."}]
        data = {"links": {leaf: {"parent": root, "source": "resume"}}, "rejected": {}, "completed": {}}
        self.assertEqual("yourturn", workstreams.make_workstreams([dict(r) for r in rows], data, {root: flag})[0]["bucket"])
        rows[1]["bucket"] = "idle"
        self.assertEqual("pending", workstreams.make_workstreams([dict(r) for r in rows], data, {root: flag})[0]["bucket"])

    def test_renamed_resume_titles_the_workstream(self):
        root = "11111111-1111-4111-8111-111111111111"
        leaf = "22222222-2222-4222-8222-222222222222"
        rows = [{"id": root, "title": "Old chat", "root": "claude", "activity": 60, "bucket": "idle", "detail": ""},
                {"id": leaf, "title": "Old chat", "root": "claude", "activity": 100, "bucket": "yourturn", "detail": ""}]
        data = {"links": {leaf: {"parent": root, "source": "resume"}}, "rejected": {}, "completed": {}}
        self.assertEqual("Old chat", workstreams.make_workstreams([dict(r) for r in rows], data)[0]["title"])
        rows[1].update(title="PL PRD split parcel checkout validation", renamed=True)
        self.assertEqual("PL PRD split parcel checkout validation",
                         workstreams.make_workstreams([dict(r) for r in rows], data)[0]["title"])


if __name__ == "__main__":
    unittest.main()
