#!/usr/bin/env python3
"""Create the local Compose secret without printing it or replacing a file."""
import os
from pathlib import Path
import secrets


def main() -> None:
    directory = Path("secrets")
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
        raise SystemExit("secrets must not be a symlink or junction")
    directory.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        # The parent protects the host token; the bind-mounted file needs to be
        # readable by the container's non-root UID. Compose ignores uid/mode
        # remapping for a local file-backed secret.
        directory.chmod(0o700)
    destination = directory / "admin-token"
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(secrets.token_urlsafe(48))
    if os.name != "nt":
        destination.chmod(0o644)  # Override a restrictive caller umask for the mount.
    print("Created secrets/admin-token; keep the secrets directory restricted to your account.")


if __name__ == "__main__":
    main()
