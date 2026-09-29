import tempfile
import unittest
from unittest import mock

import agent_board as board


SID = "00000000-0000-4000-8000-000000000002"


class ResumeNewChatTests(unittest.TestCase):
    def run_resume(self, **fields):
        with tempfile.TemporaryDirectory() as cwd:
            row = {"id": SID, "root": "projects", "cwd": cwd, **fields}
            with mock.patch.object(board, "_recent_status", (0, 0, [row])), \
                    mock.patch.object(board.sys, "platform", "darwin"), \
                    mock.patch.object(board, "CONFIG", {}), \
                    mock.patch.object(board.time, "sleep"), \
                    mock.patch.object(board.subprocess, "run") as run:
                mode = board.resume_in_new_chat(SID, 24)
            return mode, [c.args[0] for c in run.call_args_list], cwd

    def test_surface_follows_session_origin(self):
        cases = [
            ({"root": "codex", "originator": "Codex Desktop"}, "codex-app"),
            ({"root": "codex", "originator": "codex_vscode"}, "codex-vscode"),
            ({"root": "codex", "originator": "codex_cli_rs"}, "codex-cli"),
            ({"root": "projects", "entrypoint": "claude-vscode"}, "claude-vscode"),
            ({"root": "projects", "entrypoint": "cli"}, "claude-cli"),
            ({"root": "projects", "entrypoint": "sdk-cli"}, "claude-app"),
        ]
        for row, surface in cases:
            self.assertEqual(surface, board.resume_surface(row))

    def test_prompt_names_session_and_shared_snapshot(self):
        prompt = board.resume_prompt({"id": SID, "root": "codex"})
        self.assertIn("resume skill", prompt)
        self.assertIn(f".agent-handoffs/codex-{SID}.md", prompt)

    def test_claude_app_opens_new_code_chat_in_folder(self):
        mode, calls, cwd = self.run_resume(entrypoint="sdk-cli")
        self.assertEqual("sent", mode)
        url = calls[-1][1]
        self.assertTrue(url.startswith("claude://code/new?"))
        self.assertIn("q=Use%20the%20resume%20skill", url)
        self.assertIn("folder=" + board.quote(cwd), url)

    def test_codex_app_opens_new_thread_in_folder(self):
        mode, calls, cwd = self.run_resume(root="codex", originator="Codex Desktop")
        self.assertEqual("sent", mode)
        self.assertTrue(calls[-1][1].startswith("codex://new?prompt="))
        self.assertIn("path=" + board.quote(cwd), calls[-1][1])

    def test_claude_vscode_focuses_folder_then_sends_prompt(self):
        mode, calls, cwd = self.run_resume(entrypoint="claude-vscode")
        self.assertEqual("sent", mode)
        self.assertEqual(["open", "-a", "Visual Studio Code", cwd], calls[0])
        self.assertTrue(calls[1][1].startswith("vscode://anthropic.claude-code/open?prompt="))

    def test_codex_vscode_copies_prompt(self):
        mode, calls, _ = self.run_resume(root="codex", originator="codex_vscode")
        self.assertEqual("copied", mode)
        self.assertEqual(["pbcopy"], calls[0])
        self.assertEqual(["open", "vscode://openai.chatgpt/"], calls[-1])

    def test_cli_session_opens_terminal(self):
        mode, calls, _ = self.run_resume(entrypoint="cli")
        self.assertEqual("sent", mode)
        self.assertEqual("osascript", calls[0][0])
        self.assertIn("claude ", calls[0][2])

    def test_unknown_session_is_rejected(self):
        with mock.patch.object(board, "_recent_status", (0, 0, [])), \
                mock.patch.object(board, "status", return_value={"sessions": []}):
            self.assertIsNone(board.resume_in_new_chat(SID, 24))

    def test_resumed_chat_inherits_source_title(self):
        parent = "60f6d81b-0000-4000-8000-000000000001"
        linked = "00000000-0000-4000-8000-000000000003"
        rows = [
            {"id": parent, "title": "Agent board release"},
            {"id": SID, "title": "Resume session 60f6d81b"},
            {"id": linked, "title": "Use the resume skill to pick up session 00000000-0000"},
            {"id": "00000000-0000-4000-8000-000000000004", "title": "Resume BR PRD conversion"},
        ]
        board.inherit_resume_titles(rows, {linked: {"parent": SID}})
        self.assertEqual(["Agent board release", "↩ Agent board release", "↩ Agent board release",
                          "Resume BR PRD conversion"], [r["title"] for r in rows])


if __name__ == "__main__":
    unittest.main()
