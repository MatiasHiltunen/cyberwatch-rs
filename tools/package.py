#!/usr/bin/env python3
"""Build and verify the distributable Cyberwatch source archive."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "cyberwatch-rs.zip"
ARCHIVE_ROOT = "cyberwatch-rs"

REQUIRED_ARCHIVE_FILES = {
    f"{ARCHIVE_ROOT}/Cargo.toml",
    f"{ARCHIVE_ROOT}/src/main.rs",
    f"{ARCHIVE_ROOT}/src/lib.rs",
    f"{ARCHIVE_ROOT}/src/schema.sql",
    f"{ARCHIVE_ROOT}/src/ingest/nvd.rs",
    f"{ARCHIVE_ROOT}/src/ingest/cisa.rs",
    f"{ARCHIVE_ROOT}/src/ingest/feeds.rs",
    f"{ARCHIVE_ROOT}/web/index.html",
    f"{ARCHIVE_ROOT}/web/app.js",
    f"{ARCHIVE_ROOT}/README.md",
    f"{ARCHIVE_ROOT}/docs/course-map.md",
    f"{ARCHIVE_ROOT}/docs/security/threat-model.md",
    f"{ARCHIVE_ROOT}/tests/http.rs",
    f"{ARCHIVE_ROOT}/tools/check.py",
    f"{ARCHIVE_ROOT}/tools/backup.py",
    f"{ARCHIVE_ROOT}/tools/runtime_artifact.py",
    f"{ARCHIVE_ROOT}/tools/runtime_size_policy.json",
    f"{ARCHIVE_ROOT}/src/healthcheck.rs",
    f"{ARCHIVE_ROOT}/tests/healthcheck_cli.rs",
    f"{ARCHIVE_ROOT}/docs/production-size.md",
    f"{ARCHIVE_ROOT}/.github/workflows/ci.yml",
    f"{ARCHIVE_ROOT}/.github/workflows/release.yml",
    f"{ARCHIVE_ROOT}/.github/workflows/deploy.yml",
    f"{ARCHIVE_ROOT}/deploy/base/deployment.yaml",
    f"{ARCHIVE_ROOT}/monitoring/prometheus.yml",
    f"{ARCHIVE_ROOT}/.devcontainer/devcontainer.json",
    f"{ARCHIVE_ROOT}/.devcontainer/Dockerfile",
    f"{ARCHIVE_ROOT}/.devcontainer/README.md",
}

EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".ci-venv",
    ".venv",
    "secrets",
    ".secrets",
    "backups",
    "reports",
    "data",
    "dist",
}
EXCLUDED_NAMES = {
    ".env",
    "cyberwatch.db",
    "cyberwatch.db-shm",
    "cyberwatch.db-wal",
}


def include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part.casefold() in EXCLUDED_PARTS for part in relative.parts):
        return False
    # Never follow a source symlink/junction into data or outside the source tree.
    for ancestor in (path, *path.parents):
        if ancestor == ROOT:
            break
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            return False
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if name in EXCLUDED_NAMES:
        return False
    if name.startswith(".env") and name != ".env.example":
        return False
    if suffix in {".pem", ".key", ".pfx", ".p12", ".zip", ".exe", ".pdb", ".rlib", ".rmeta", ".o", ".a"} or name.endswith(("-wal", "-shm", "-journal", ".tar.gz")):
        return False
    if suffix in {".pyc", ".db", ".sqlite", ".sqlite3"}:
        return False
    return path.is_file()


def main() -> int:
    subprocess.run(
        [sys.executable, str(ROOT / "tools/validate_project.py")],
        cwd=ROOT,
        check=True,
    )

    files = sorted(path for path in ROOT.rglob("*") if include(path))
    if not files:
        raise RuntimeError("refusing to create an empty source archive")

    temporary = OUTPUT.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(
        temporary,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, f"{ARCHIVE_ROOT}/{relative}")

    with zipfile.ZipFile(temporary) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED_ARCHIVE_FILES - names)
        if missing:
            raise RuntimeError(
                "archive is missing required source files: " + ", ".join(missing)
            )
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"archive CRC validation failed for {bad}")
        source_count = sum(
            name.startswith(f"{ARCHIVE_ROOT}/src/") and name.endswith(".rs")
            for name in names
        )
        if source_count < 15:
            raise RuntimeError(
                f"archive contains only {source_count} Rust source files; expected at least 15"
            )

    temporary.replace(OUTPUT)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    checksum = OUTPUT.with_suffix(OUTPUT.suffix + ".sha256")
    checksum.write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")

    print(f"Created {OUTPUT}")
    print(f"Files: {len(files)}")
    print(f"Rust source files: {source_count}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
