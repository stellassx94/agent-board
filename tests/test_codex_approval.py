import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_board as board


SID = "00000000-0000-4000-8000-000000000001"
START = "2026-09-27T07:00:00Z"
CALL = "2026-09-27T07:00:01Z"
OUTPUT = "2026-09-27T07:00:15Z"


def record(timestamp, kind, payload):
    return json.dumps({"timestamp": timestamp, "type": kind, "payload": payload})


class CodexApprovalTests(unittest.TestCase):
    def parse(self, call, followup=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"rollout-{SID}.jsonl"
            rows = [
                record(START, "session_meta", {"id": SID, "cwd": tmp}),
                record(START, "event_msg", {"type": "task_started"}),
                record(CALL, "response_item", {"type": call[0], "name": call[1],
                                                "call_id": "call-1", call[2]: call[3]}),
            ]
            if followup:
                rows.append(record(OUTPUT, *followup))
            path.write_text("\n".join(rows) + "\n")
            with mock.patch.object(board, "_cache", {}), mock.patch.object(board, "codex_titles", return_value={}):
                return board.parse_codex(path)

    def test_direct_escalation_enters_attention_after_grace(self):
        call = ("function_call", "exec_command", "arguments",
                json.dumps({"cmd": "echo ok", "sandbox_permissions": "require_escalated"}))
        row = self.parse(call)
        self.assertEqual("running", board.classify(row, board.ts(CALL) + 9, [])[0])
        self.assertEqual(("asking", "May be awaiting approval. Open the session to check."),
                         board.classify(row, board.ts(CALL) + 10, []))
        self.assertEqual("asking", board.board_bucket({"completed": False, "choice": None,
                                                       "state": "asking", "flag": None, "suggestion": None}))
        answered = self.parse(call, ("response_item", {"type": "function_call_output",
                                                       "call_id": "call-1", "output": "ok"}))
        self.assertEqual("working", board.classify(answered, board.ts(OUTPUT) + 1, [])[0])

    def test_wrapper_escalation_and_completion(self):
        call = ("custom_tool_call", "exec", "input",
                'const r=await tools.exec_command({cmd:"gh release view",'
                'sandbox_permissions:"require_escalated",justification:"May I verify?"});text(r)')
        row = self.parse(call)
        self.assertEqual("asking", board.classify(row, board.ts(CALL) + 11, [])[0])
        finished = self.parse(call, ("event_msg", {"type": "task_complete"}))
        self.assertEqual([], finished["pending"])
        self.assertEqual("yourturn", board.classify(finished, board.ts(OUTPUT) + 1, [])[0])
        replied = self.parse(call, ("event_msg", {"type": "user_message", "message": "approved"}))
        self.assertEqual([], replied["pending"])
        self.assertEqual("working", board.classify(replied, board.ts(OUTPUT) + 1, [])[0])

    def test_ordinary_and_merely_mentioned_escalations_stay_running(self):
        calls = [
            ("function_call", "exec_command", "arguments", json.dumps({"cmd": "echo ok"})),
            ("custom_tool_call", "exec", "input",
             'text("sandbox_permissions:\\"require_escalated\\" is documented here")'),
            ("function_call", "other_tool", "arguments",
             json.dumps({"sandbox_permissions": "require_escalated"})),
        ]
        for call in calls:
            with self.subTest(call=call):
                row = self.parse(call)
                self.assertEqual("running", board.classify(row, board.ts(CALL) + 11, [])[0])


if __name__ == "__main__":
    unittest.main()
