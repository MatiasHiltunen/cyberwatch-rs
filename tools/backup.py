#!/usr/bin/env python3
"""Consistent SQLite snapshots and restore into a NEW file; no third-party modules.

Run only in a directory owned by the operator; path validation does not defend
against a malicious local user concurrently replacing directory components.
The restore acknowledgement is a human interlock, not process detection.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import time


def safe_path(value: str | Path) -> Path:
    path = Path(os.path.abspath(value))
    for component in (path, *path.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError(f"symlink/junction paths are not accepted: {component}")
    return path


def source_path(value: str | Path) -> Path:
    path = safe_path(value)
    if not path.exists() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("source must be an existing regular SQLite database file")
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("source is not a SQLite database")
    return path


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def integrity(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key check failed")


def details(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def verify(value: str | Path) -> dict:
    path = source_path(value)
    with closing(readonly(path)) as connection:
        integrity(connection)
    return {"operation": "verify", "integrity": "ok", **details(path)}


def snapshot(source: str | Path, destination: str | Path, *, timeout: float = 120) -> dict:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    start = time.monotonic()
    source = source_path(source)
    destination = safe_path(destination)
    if not destination.parent.is_dir():
        raise ValueError("destination parent must already be an operator-owned directory")
    if destination.exists():
        raise ValueError("destination exists; choose a NEW filename (overwriting is disabled)")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(destination) + suffix)
        if os.path.lexists(sidecar):
            raise ValueError(f"destination has a SQLite sidecar; choose a NEW filename: {sidecar}")

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() - start > timeout:
            raise TimeoutError("backup deadline exceeded; no destination was published")

    descriptor, name = tempfile.mkstemp(prefix=".cyberwatch-backup-", suffix=".db", dir=destination.parent)
    temporary = Path(name)
    os.close(descriptor)
    try:
        with closing(readonly(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            # Publish one standalone file, never a main DB that depends on WAL.
            dst.execute("PRAGMA journal_mode=DELETE")
            integrity(dst)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        # Hard link is atomic and refuses an existing destination, including a
        # symlink created since the preflight. Temp and destination share a disk.
        os.link(temporary, destination)
        if os.name != "nt":
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return {
            "operation": "backup", "integrity": "ok",
            "elapsed_seconds": round(time.monotonic() - start, 3),
            **details(destination),
        }
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)


def restore(source: str | Path, destination: str | Path, *, app_stopped: bool, timeout: float = 120) -> dict:
    if not app_stopped:
        raise ValueError("stop ALL application writers and pass --app-stopped before restoring")
    result = snapshot(source, destination, timeout=timeout)
    result["operation"] = "restore"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("backup", "restore"):
        command = commands.add_parser(operation)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path)
        command.add_argument("--timeout", type=float, default=120)
        if operation == "restore":
            command.add_argument("--app-stopped", action="store_true")
    check = commands.add_parser("verify")
    check.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "verify":
            result = verify(args.source)
        elif args.operation == "restore":
            result = restore(args.source, args.destination, app_stopped=args.app_stopped, timeout=args.timeout)
        else:
            result = snapshot(args.source, args.destination, timeout=args.timeout)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error, TimeoutError) as error:
        print(f"{args.operation} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
