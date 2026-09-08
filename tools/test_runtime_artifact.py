import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from runtime_artifact import PAYLOAD, read_payload, write_bundle


class RuntimeArtifactTests(unittest.TestCase):
    def make_rootfs(self, path, extra=None, machine=183, symlink=False):
        binary = bytearray(64)
        binary[:6] = b"\x7fELF\x02\x01"
        binary[18:20] = machine.to_bytes(2, "little")
        with tarfile.open(path, "w") as archive:
            for name in [*PAYLOAD, *([extra] if extra else [])]:
                member = tarfile.TarInfo(name)
                data = bytes(binary) if name.endswith("/cyberwatch-rs") else b"fixture"
                member.size = len(data)
                if symlink and name.endswith("/cyberwatch-rs"):
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/outside"
                    member.size = 0
                archive.addfile(member, io.BytesIO(data))

    def test_runtime_archive_is_minimal_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rootfs.tar"
            self.make_rootfs(source)
            payload = read_payload(source, "arm64", {"binary_max_bytes": 1024})
            first, second = root / "first.tar.gz", root / "second.tar.gz"
            self.assertEqual(write_bundle(payload, first), write_bundle(payload, second))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                self.assertEqual(set(archive.getnames()), {"cyberwatch-rs/" + name for name in PAYLOAD.values()})
                self.assertEqual(archive.getmember("cyberwatch-rs/cyberwatch-rs").mode, 0o755)

    def test_rejects_runtime_tooling_wrong_architecture_and_symlinks(self):
        cases = [{"extra": "usr/bin/python3"}, {"extra": "bin/sh"}, {"extra": "app/tools/backup.py"},
                 {"machine": 62}, {"symlink": True}]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rootfs.tar"
            for case in cases:
                with self.subTest(case=case):
                    self.make_rootfs(source, **case)
                    with self.assertRaises(ValueError):
                        read_payload(source, "arm64", {"binary_max_bytes": 1024})

    def test_rejects_oversize_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rootfs.tar"
            self.make_rootfs(source)
            with self.assertRaisesRegex(ValueError, "size limit"):
                read_payload(source, "arm64", {"binary_max_bytes": 32})


if __name__ == "__main__":
    unittest.main()
