"""Exercise real SQLite WAL snapshots, recovery and failure atomicity."""
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cyberwatch recovery ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "live # database.db"
        self.connection = sqlite3.connect(self.source)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, text TEXT)")
        self.connection.execute("INSERT INTO records VALUES(1, 'Finnish: hälytys')")
        self.connection.commit()

    def test_wal_round_trip_preserves_committed_snapshot_only(self):
        self.assertTrue(Path(str(self.source) + "-wal").exists())
        archive = self.root / "backup.db"
        restored = self.root / "restored.db"
        result = backup.snapshot(self.source, archive)
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(len(result["sha256"]), 64)
        self.connection.execute("INSERT INTO records VALUES(2, 'after backup')")
        self.connection.commit()
        self.assertEqual(backup.restore(archive, restored, app_stopped=True)["operation"], "restore")
        with closing(sqlite3.connect(restored)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM records").fetchall(), [(1, "Finnish: hälytys")])
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.assertEqual(backup.verify(restored)["integrity"], "ok")
        self.assertFalse(Path(str(archive) + "-wal").exists())

    def test_never_overwrites_and_requires_shutdown_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "NEW filename"):
            backup.snapshot(self.source, self.source)
        existing = self.root / "important.db"
        existing.write_bytes(b"keep this")
        with self.assertRaises(ValueError):
            backup.restore(self.source, existing, app_stopped=True)
        self.assertEqual(existing.read_bytes(), b"keep this")
        with self.assertRaisesRegex(ValueError, "stop ALL"):
            backup.restore(self.source, self.root / "new.db", app_stopped=False)

    def test_corrupt_input_and_missing_source_do_not_create_destination(self):
        bad = self.root / "bad.db"
        bad.write_bytes(b"SQLite format 3\0" + b"broken" * 100)
        for source in (bad, self.root / "missing.db"):
            with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                backup.snapshot(source, self.root / "result.db")
            self.assertFalse((self.root / "result.db").exists())
        self.assertEqual(list(self.root.glob(".cyberwatch-backup-*")), [])

    def test_foreign_key_violation_is_rejected(self):
        self.connection.executescript("CREATE TABLE child(parent INTEGER REFERENCES records(id)); INSERT INTO child VALUES(99);")
        with self.assertRaisesRegex(ValueError, "foreign key"):
            backup.snapshot(self.source, self.root / "invalid.db")
        self.assertFalse((self.root / "invalid.db").exists())

    def test_refuses_stale_wal_at_destination(self):
        (self.root / "result.db-wal").write_bytes(b"old WAL")
        with self.assertRaisesRegex(ValueError, "sidecar"):
            backup.snapshot(self.source, self.root / "result.db")

    def test_symlink_source_or_destination_is_rejected(self):
        link = self.root / "link.db"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("host does not permit symlink creation")
        with self.assertRaisesRegex(ValueError, "symlink"):
            backup.snapshot(link, self.root / "result.db")
        with self.assertRaisesRegex(ValueError, "symlink"):
            backup.snapshot(self.source, link)

    def test_publish_race_cannot_replace_an_existing_destination(self):
        destination = self.root / "raced.db"
        original_link = backup.os.link

        def raced_link(source, target):
            destination.write_bytes(b"created by someone else")
            original_link(source, target)

        with patch.object(backup.os, "link", side_effect=raced_link):
            with self.assertRaises(FileExistsError):
                backup.snapshot(self.source, destination)
        self.assertEqual(destination.read_bytes(), b"created by someone else")
        self.assertEqual(list(self.root.glob(".cyberwatch-backup-*")), [])

    def test_timeout_does_not_publish_partial_backup(self):
        with patch.object(backup.time, "monotonic", side_effect=[0, 999]):
            with self.assertRaises(TimeoutError):
                backup.snapshot(self.source, self.root / "timeout.db", timeout=1)
        self.assertFalse((self.root / "timeout.db").exists())

    def test_cli_failure_returns_nonzero(self):
        result = subprocess.run([sys.executable, str(Path(backup.__file__)), "restore", str(self.source), str(self.root / "new.db")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--app-stopped", result.stderr)


if __name__ == "__main__":
    unittest.main()
