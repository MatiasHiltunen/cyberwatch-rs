#!/usr/bin/env python3
"""Stage a development admin token in a private Linux home directory; never echo it.

Local mode needs no cloud account. Key Vault mode requires an explicit developer
login and an existing development vault. This is not a production secret agent.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile


def private_directory(home: Path) -> Path:
    if os.name != "posix":
        raise ValueError("Run this helper inside the Linux Dev Container; Windows ACLs are not configured by it.")
    directory = home / "secrets"
    if directory.is_symlink():
        raise ValueError("Secret directory must not be a symlink.")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.stat().st_uid != os.getuid():
        raise ValueError("Secret directory must belong to the current user.")
    directory.chmod(0o700)
    return directory


def validate(value: str) -> str:
    value = value.strip()
    if not value.isascii() or not 32 <= len(value) <= 16384 or any(c.isspace() for c in value):
        raise ValueError("Admin token must be 32–16384 ASCII characters without whitespace.")
    return value


def stage(directory: Path, name: str, value: str) -> Path:
    value = validate(value)
    destination = directory / name
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("Secret destination must be a regular file.")
    descriptor, temporary = tempfile.mkstemp(prefix=".token-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(value)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def az_json(arguments: list[str]):
    try:
        result = subprocess.run(["az", *arguments, "--output", "json", "--only-show-errors"],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Azure CLI is unavailable or timed out; no token was written.") from None
    if result.returncode:
        # Azure responses may contain sensitive data. Never forward child output.
        raise ValueError("Azure request failed. Check login, vault name, RBAC and network access; no token was written.")
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError("Azure returned an unexpected response; no token was written.") from None


def fetch(vault: str, name: str, subscription: str, version: str | None) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]", vault):
        raise ValueError("Invalid Key Vault name.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", name):
        raise ValueError("Invalid secret name.")
    if version and not re.fullmatch(r"[A-Fa-f0-9]{32}", version):
        raise ValueError("Invalid secret version.")
    # Confirm that the named vault belongs to the explicitly selected subscription.
    vault_id = az_json(["keyvault", "show", "--name", vault, "--subscription", subscription, "--query", "id"])
    if not isinstance(vault_id, str) or not vault_id.lower().startswith(f"/subscriptions/{subscription.lower()}/"):
        raise ValueError("Vault is outside the selected subscription; no token was written.")
    command = ["keyvault", "secret", "show", "--vault-name", vault, "--name", name,
               "--subscription", subscription, "--query", "value"]
    if version:
        command += ["--version", version]
    value = az_json(command)
    if not isinstance(value, str):
        raise ValueError("Azure returned no secret value; no token was written.")
    return validate(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("local", help="create or validate the existing offline development token")
    cloud = commands.add_parser("keyvault", help="copy only a development admin token from an existing vault")
    cloud.add_argument("--vault", required=True)
    cloud.add_argument("--secret", required=True)
    cloud.add_argument("--subscription", required=True, help="subscription UUID, not its display name")
    cloud.add_argument("--version", help="optional immutable secret version")
    args = parser.parse_args()
    try:
        directory = private_directory(Path.home())
        if args.mode == "local":
            path = directory / "admin-token"
            if path.is_symlink():
                raise ValueError("Secret destination must not be a symlink.")
            if path.exists():
                if path.stat().st_size > 16384:
                    raise ValueError("Existing development token is too large.")
                validate(path.read_text(encoding="ascii"))
                path.chmod(0o600)
            else:
                path = stage(directory, "admin-token", secrets.token_urlsafe(48))
        else:
            value = fetch(args.vault, args.secret, args.subscription, args.version)
            path = stage(directory, "keyvault-admin-token", value)
        print(f"Development token file ready: {path}. No value printed. Restart the app to use this file.")
    except (ValueError, OSError):
        # Deliberately do not print an exception that could embed a secret/path input.
        raise SystemExit("Secret setup failed. Check the documented prerequisites; secret values and child output are suppressed.") from None


if __name__ == "__main__":
    main()
