import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_board_workstreams as ws


OLD = "00000000-0000-4000-8000-000000000001"
NEW = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"


class CaptureToolTests(unittest.TestCase):
    def run_hook(self, payload, lineage):
        with mock.patch.object(ws, "DATA_FILE", lineage), \
                mock.patch.object(ws.sys, "argv", ["x", "capture-tool"]), \
                mock.patch.object(ws.sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("builtins.print"):
            ws.main()
            return ws.load()["links"]

    def test_marker_command_links_at_once(self):
        with tempfile.TemporaryDirectory() as d:
            cmd = "/usr/bin/python3 ~/x/agent_board_workstreams.py resume-source claude-" + OLD
            links = self.run_hook({"session_id": NEW, "tool_input": {"command": cmd}}, Path(d) / "l.json")
            self.assertEqual(links[NEW]["parent"], OLD)

    def test_other_commands_and_self_links_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            lineage = Path(d) / "l.json"
            self.assertEqual(self.run_hook({"session_id": NEW, "tool_input": {"command": "ls"}}, lineage), {})
            cmd = "agent_board_workstreams.py resume-source " + NEW
            self.assertEqual(self.run_hook({"session_id": NEW, "tool_input": {"command": cmd}}, lineage), {})

    def test_existing_link_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            lineage = Path(d) / "l.json"
            lineage.write_text(json.dumps({"links": {NEW: {"parent": OTHER, "source": "manual", "at": 1}}}))
            cmd = "agent_board_workstreams.py resume-source codex-" + OLD
            links = self.run_hook({"session_id": NEW, "tool_input": {"command": cmd}}, lineage)
            self.assertEqual(links[NEW]["parent"], OTHER)


if __name__ == "__main__":
    unittest.main()
