#!/usr/bin/env python3
"""Prepare the private development token and locked Cargo dependencies."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare_token():
    home = Path.home()
    directory = home / "secrets"
    token = directory / "admin-token"
    if os.environ.get("ADMIN_TOKEN_FILE") != str(token):
        raise SystemExit("Run setup in the configured Dev Container (ADMIN_TOKEN_FILE must match its home).")
    if directory.is_symlink() or token.is_symlink():
        raise SystemExit("Development secret paths must not be symlinks.")
    if not token.exists():
        subprocess.run([sys.executable, str(ROOT / "tools/create_admin_secret.py")], cwd=home, check=True)
    if not token.is_file() or token.stat().st_size > 16384 or len(token.read_text(encoding="ascii").strip()) < 32:
        raise SystemExit("The existing development token is invalid; inspect it locally before replacing it.")
    directory.chmod(0o700)
    token.chmod(0o600)
    print("Private development admin token is ready.", flush=True)


if __name__ == "__main__":
    prepare_token()
    subprocess.run(["cargo", "fetch", "--locked"], cwd=ROOT, check=True)
