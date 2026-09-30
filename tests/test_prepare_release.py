import importlib.util
from io import BytesIO
from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "macos/prepare_release.py"
spec = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PrepareReleaseTests(unittest.TestCase):
    def test_public_text_and_binary_asset_pass(self):
        release.scan_source("README.md", b"Install from a reviewed release.")
        release.scan_source("icon.png", b"\x89PNG\r\n\x1a\n\xff")

    def test_personal_path_and_state_are_rejected(self):
        personal = b"home = " + b"/Users/" + b"someone/private"
        with self.assertRaisesRegex(ValueError, "personal home path"):
            release.scan_source("README.md", personal)
        with self.assertRaisesRegex(ValueError, "Personal state"):
            release.scan_source("agent_board_completed.json", b"{}")

    def test_archive_entries_are_scanned(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("notes/config.json", "{}")
        with self.assertRaisesRegex(ValueError, "Personal state"):
            release.scan_source("docs/colleague-intro.zip", buffer.getvalue())

    def test_inline_script_is_found(self):
        collector = release.ScriptCollector()
        collector.feed("<script>const ready = true;</script>")
        self.assertEqual(collector.scripts, ["const ready = true;"])

    def test_app_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = Path(tmp) / "Contents/Info.plist"
            info.parent.mkdir()
            info.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.4.8"}))
            with self.assertRaisesRegex(ValueError, "app version differs"):
                release.assert_safe_bundle(Path(tmp), "v0.4.9")

    def test_sidebar_version_must_match_the_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "vscode-extension/package.json"
            package.parent.mkdir()
            package.write_text('{"version": "0.4.8"}')
            with self.assertRaisesRegex(ValueError, "sidebar version 0.4.8 differs"):
                release.check_sidebar_version("v0.4.9", Path(tmp))
            release.check_sidebar_version("v0.4.8", Path(tmp))


if __name__ == "__main__":
    unittest.main()
