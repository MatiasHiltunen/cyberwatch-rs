#!/usr/bin/env python3
"""Cross-platform entry point for the checks also executed by CI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="only Python, manifest and JavaScript checks")
    args = parser.parse_args()
    commands = [[sys.executable, "tools/validate_project.py"],
                [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"],
                [sys.executable, "tools/policy_check.py"], ["node", "--check", "web/app.js"]]
    if not args.static:
        commands += [["cargo", "fmt", "--all", "--", "--check"],
                     ["cargo", "clippy", "--locked", "--all-targets", "--all-features", "--", "-D", "clippy::correctness"],
                     ["cargo", "test", "--locked", "--all-targets", "--all-features"],
                     ["cargo", "build", "--locked"]]
    for command in commands:
        if not shutil.which(command[0]):
            raise SystemExit(f"Required tool unavailable: {command[0]}")
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    if not args.static:
        metadata = json.loads(subprocess.check_output(
            ["cargo", "metadata", "--format-version", "1", "--no-deps", "--locked"],
            cwd=ROOT, text=True,
        ))
        binary = Path(metadata["target_directory"]) / "debug" / (
            "cyberwatch-rs.exe" if sys.platform == "win32" else "cyberwatch-rs"
        )
        command = [sys.executable, "tools/smoke.py", "--binary", str(binary)]
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
