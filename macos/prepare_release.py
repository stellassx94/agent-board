#!/usr/bin/env python3
"""Prepare and verify a local Agent Board package without publishing it."""

import argparse
from html.parser import HTMLParser
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parent.parent
PYTHON_SOURCES = (
    "agent_board.py",
    "agent_board_classify.py",
    "agent_board_workstreams.py",
    "macos/prepare_release.py",
)
PRIVATE_PATTERNS = {
    "personal home path": re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
    "credential": re.compile(
        r"(?:gh" + r"[opusr]_|github" + r"_pat_|gl" + r"pat-|"
        r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)"
    ),
}
STATE_NAMES = {
    "config.json", "custom.css", "agent_board_completed.json",
    "agent_board_choices.json", "agent_board_flags.json",
    "agent_board_suggestions.json", "agent_board_lineage.json",
    "agent_board_prompts.json", "agent_board_topics.json",
    "agent_board_topic_choices.json",
}


def run(*args, env=None, input=None, capture=False, timeout=600):
    return subprocess.run(
        args, cwd=ROOT, env=env, input=input, text=True,
        check=True, capture_output=capture, timeout=timeout,
    )


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data


def scan_source(name, content):
    path = Path(name)
    if path.name in STATE_NAMES or path.suffix in {".jsonl", ".log", ".pem", ".key"}:
        raise ValueError(f"Personal state or credential file in source: {name}")
    if path.suffix == ".zip":
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if member.file_size > 20_000_000:
                    raise ValueError(f"Unusually large archive entry: {name}/{member.filename}")
                scan_source(f"{name}/{member.filename}", archive.read(member))
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return
    for label, pattern in PRIVATE_PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f"Possible {label} in {name}; review before packaging")


def check_sources():
    for name in PYTHON_SOURCES:
        compile((ROOT / name).read_bytes(), name, "exec")
    print("Python syntax: OK", flush=True)

    collector = ScriptCollector()
    collector.feed((ROOT / "agent_board.py").read_text())
    if not collector.scripts:
        raise ValueError("No embedded JavaScript found")
    for script in collector.scripts:
        run("node", "--check", input=script, timeout=30)
    print("Embedded JavaScript syntax: OK", flush=True)

    run("git", "diff", "--check", timeout=30)
    run("git", "diff", "--cached", "--check", timeout=30)
    names = run(
        "git", "ls-files", "--cached", "--others", "--exclude-standard", "-z",
        capture=True, timeout=30,
    ).stdout.split("\0")
    for name in filter(None, names):
        path = ROOT / name
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink in source: {name}")
        if not path.is_file():
            continue
        scan_source(name, path.read_bytes())
    print("Diff and source privacy scan: OK", flush=True)


def check_sidebar_version(version, root=ROOT):
    """The VS Code sidebar ships with the app, so both carry one version."""
    sidebar = json.loads((root / "vscode-extension/package.json").read_text()).get("version")
    if sidebar != version.removeprefix("v"):
        raise ValueError(f"VS Code sidebar version {sidebar} differs from VERSION {version}")
    print("Sidebar version: OK", flush=True)


def check_clean_profile(executable, version):
    with tempfile.TemporaryDirectory(prefix="agent-board-profile-") as tmp:
        tmp = Path(tmp)
        config = tmp / "config.json"
        config.write_text(json.dumps({
            "claude_roots": [str(tmp / "claude")],
            "codex_dir": str(tmp / "codex"),
        }))
        env = os.environ.copy()
        env.update(AGENT_BOARD_CONFIG=str(config), AGENT_BOARD_DATA_DIR=str(tmp / "state"))
        command = (sys.executable, str(executable)) if executable.suffix == ".py" else (str(executable),)
        output = run(*command, "--once", env=env, capture=True, timeout=60).stdout
        data = json.loads(output)
        if data.get("version") != version or data.get("sessions") or data.get("workstreams"):
            raise ValueError("Clean profile must report the expected version and zero sessions/workstreams")
    print(f"Clean profile ({executable.name}): OK", flush=True)


def assert_safe_bundle(app, version):
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleShortVersionString") != version.removeprefix("v"):
        raise ValueError("Mac app version differs from VERSION")
    backend = app / "Contents/Resources/Backend"
    for name in ("agent_board.py", "agent_board_classify.py", "agent_board_workstreams.py", "VERSION"):
        if (ROOT / name).read_bytes() != (backend / name).read_bytes():
            raise ValueError(f"Bundled {name} differs from source")
    for path in app.rglob("*"):
        if path.name in STATE_NAMES or path.suffix in {".jsonl", ".log", ".pem", ".key"}:
            raise ValueError(f"Personal state or credential file in app: {path.relative_to(app)}")
    run("codesign", "--verify", "--deep", "--strict", str(app), timeout=60)


def prepare(version):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This release package requires an Apple Silicon Mac")
    for tool in ("uvx", "xcrun", "node", "codesign", "ditto"):
        if not shutil.which(tool):
            raise ValueError(f"Missing build tool: {tool}")
    with tempfile.TemporaryDirectory(prefix="agent-board-prepare-") as tmp:
        tmp = Path(tmp)
        app = tmp / "Agent Board.app"
        env = os.environ.copy()
        env["AGENT_BOARD_APP_PATH"] = str(app)
        env["AGENT_BOARD_BUILD_CACHE"] = str(tmp / "cache")
        env.pop("AGENT_BOARD_BUNDLE_RUNTIME", None)
        print("Building local app (no install or publish)...", flush=True)
        run("sh", "macos/build.sh", env=env)
        assert_safe_bundle(app, version)
        check_clean_profile(app / "Contents/Resources/BackendExecutable/agent-board-service", version)

        archive = tmp / f"Agent-Board-{version}-macos-arm64.zip"
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive))
        extracted = tmp / "extracted"
        extracted.mkdir()
        run("ditto", "-x", "-k", str(archive), str(extracted))
        unpacked = extracted / "Agent Board.app"
        assert_safe_bundle(unpacked, version)
        if sorted(p.name for p in extracted.iterdir()) != ["Agent Board.app"]:
            raise ValueError("ZIP contains unexpected top-level files")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()

        output = ROOT / "build" / f"prepared-{version}-{time.strftime('%Y%m%d-%H%M%S')}"
        output.mkdir(parents=True, exist_ok=False)
        destination = output / archive.name
        shutil.copy2(archive, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError("Copied ZIP differs from verified archive")
    print(f"Prepared ZIP: {destination}", flush=True)
    print(f"SHA-256: {digest}", flush=True)
    print("Local preparation complete. Nothing was installed or published.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="run checks without building")
    args = parser.parse_args()
    try:
        version = (ROOT / "VERSION").read_text().strip()
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
            raise ValueError("VERSION must be vMAJOR.MINOR.PATCH")
        print(f"Checking Agent Board {version}...", flush=True)
        run(sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q")
        check_sources()
        check_sidebar_version(version)
        check_clean_profile(ROOT / "agent_board.py", version)
        if not args.check_only:
            prepare(version)
        else:
            print("Checks complete. No build, install, or publication.", flush=True)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Preparation stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
