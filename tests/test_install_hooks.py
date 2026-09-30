import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_board as board


class InstallHooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.backend = root / "App Folder" / "Backend"
        self.backend.mkdir(parents=True)
        for name in ("agent_board_classify.py", "agent_board_workstreams.py"):
            (self.backend / name).write_text("")
        (root / "claude").mkdir()
        self.settings = root / "claude" / "settings.json"
        self.data = root / "state"
        patches = (
            mock.patch.object(board, "CLAUDE_SETTINGS", self.settings),
            mock.patch.object(board, "DATA_DIR", self.data),
            mock.patch.object(board, "hook_backend_dir", lambda: self.backend),
            mock.patch.dict(board.os.environ, {}, clear=False),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        board.os.environ.pop("AGENT_BOARD_DATA_DIR", None)
        self.addCleanup(self.tmp.cleanup)

    def commands(self, event):
        return list(board.hook_commands(json.loads(self.settings.read_text()), event))

    def test_status_lists_every_hook_when_settings_are_absent(self):
        status = board.hook_status()
        self.assertTrue(status["available"])
        self.assertEqual(len(status["missing"]), len(board.HOOK_SPECS))

    def test_status_is_unavailable_without_claude_code_or_scripts(self):
        self.settings.write_text("[]")
        self.assertFalse(board.hook_status()["available"])
        self.settings.unlink()
        (self.backend / "agent_board_classify.py").unlink()
        self.assertFalse(board.hook_status()["available"])

    def test_install_adds_all_hooks_keeps_other_settings_and_backs_up(self):
        original = {
            "model": "x",
            "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]},
        }
        self.settings.write_text(json.dumps(original))
        board.install_hooks()
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["model"], "x")
        self.assertEqual(board.hook_status()["missing"], [])
        bash = saved["hooks"]["PostToolUse"]
        self.assertEqual(len(bash), 1)
        self.assertEqual(bash[0]["hooks"][0]["command"], "echo mine")
        self.assertIn("capture-tool", bash[0]["hooks"][1]["command"])
        self.assertEqual(saved["hooks"]["Notification"][0]["matcher"], "permission_prompt")
        self.assertNotIn("matcher", saved["hooks"]["Stop"][0])
        self.assertEqual(len(self.commands("Stop")), 2)
        backups = list((self.data / "backups").glob("claude-settings-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), original)

    def test_install_replaces_old_agent_board_hooks_and_is_repeatable(self):
        self.settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": '/usr/bin/python3 "/old/place/agent_board_classify.py"'},
            {"type": "command", "command": "echo keep"},
        ]}]}}))
        self.assertIn("completion suggestions", board.hook_status()["missing"])
        board.install_hooks()
        board.install_hooks()
        stop = self.commands("Stop")
        self.assertEqual(len(stop), 3)
        self.assertIn("echo keep", stop)
        self.assertFalse(any("/old/place/" in c for c in stop))
        self.assertTrue(all(str(self.backend) in c for c in stop if c != "echo keep"))
        self.assertEqual(len(self.commands("PostToolUse")), 1)
        self.assertEqual(len(self.commands("Notification")), 1)

    def test_install_refuses_settings_it_cannot_read(self):
        self.settings.write_text("{not json")
        with self.assertRaises(ValueError):
            board.install_hooks()
        self.assertEqual(self.settings.read_text(), "{not json")


if __name__ == "__main__":
    unittest.main()
