#!/usr/bin/env python3
"""Dependency-free structural validation for the Cyberwatch source bundle."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "Cargo.toml",
    "README.md",
    "ARCHITECTURE.md",
    ".env.example",
    "src/main.rs",
    "src/lib.rs",
    "src/api.rs",
    "src/config.rs",
    "src/db.rs",
    "src/models.rs",
    "src/refresh.rs",
    "src/schema.sql",
    "src/ingest/mod.rs",
    "src/ingest/source.rs",
    "src/ingest/http.rs",
    "src/ingest/nvd.rs",
    "src/ingest/cisa.rs",
    "src/ingest/github.rs",
    "src/ingest/feeds.rs",
    "src/ingest/epss.rs",
    "src/ingest/validate.rs",
    "web/index.html",
    "web/styles.css",
    "web/app.js",
    "sources.default.json",
    "Dockerfile",
    "tools/package.py",
]


def fail(message: str) -> None:
    raise RuntimeError(message)


def check_required() -> None:
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        fail(f"missing required project files: {', '.join(missing)}")


def check_manifest() -> None:
    data = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    package = data.get("package", {})
    if package.get("name") != "cyberwatch-rs":
        fail("Cargo package name is not cyberwatch-rs")
    if not data.get("dependencies", {}).get("libsql"):
        fail("Cargo manifest does not include the local Turso/libSQL dependency")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    if "COPY sources.default.json ./" not in dockerfile:
        fail("Dockerfile does not copy the catalog required by include_str!")


def check_json() -> None:
    for path in sorted(ROOT.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "sources.default.json").read_text(encoding="utf-8"))
    feeds = catalog.get("feeds", [])
    ids = [feed["id"] for feed in feeds]
    names = [feed["name"].casefold() for feed in feeds]
    if len(feeds) < 25:
        fail("default source catalog contains fewer than 25 feeds")
    if len(ids) != len(set(ids)):
        fail("default source catalog contains duplicate IDs")
    if len(names) != len(set(names)):
        fail("default source catalog contains duplicate names")


def check_schema() -> None:
    sql = (ROOT / "src/schema.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(sql)
        required_tables = {
            "items",
            "item_categories",
            "item_cves",
            "cve_evidence",
            "cve_validation",
            "ingestion_runs",
            "sync_state",
            "source_cache",
        }
        actual = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(required_tables - actual)
        if missing:
            fail(f"schema is missing tables: {', '.join(missing)}")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            fail("SQLite schema integrity check failed")
    finally:
        connection.close()


def check_rust_delimiters() -> int:
    scanned = 0
    for path in sorted((ROOT / "src").rglob("*.rs")):
        scan_rust(path)
        scanned += 1
    return scanned


def scan_rust(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    i = 0
    line = 1
    block_comment_depth = 0
    state = "normal"
    raw_hashes = 0

    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if char == "\n":
            line += 1

        if state == "line-comment":
            if char == "\n":
                state = "normal"
            i += 1
            continue
        if state == "block-comment":
            if char == "/" and nxt == "*":
                block_comment_depth += 1
                i += 2
                continue
            if char == "*" and nxt == "/":
                block_comment_depth -= 1
                i += 2
                if block_comment_depth == 0:
                    state = "normal"
                continue
            i += 1
            continue
        if state == "string":
            if char == "\\":
                i += 2
                continue
            if char == '"':
                state = "normal"
            i += 1
            continue
        if state == "char":
            if char == "\\":
                i += 2
                continue
            if char == "'":
                state = "normal"
            i += 1
            continue
        if state == "raw":
            if char == '"' and text.startswith("#" * raw_hashes, i + 1):
                # The loop increment consumes the quote; skip only the hashes here.
                i += raw_hashes
                state = "normal"
            i += 1
            continue

        if char == "/" and nxt == "/":
            state = "line-comment"
            i += 2
            continue
        if char == "/" and nxt == "*":
            state = "block-comment"
            block_comment_depth = 1
            i += 2
            continue
        # Raw strings must be recognized before ordinary string literals.
        if char == "r":
            match = re.match(r'r(#+)?"', text[i:])
            if match:
                raw_hashes = len(match.group(1) or "")
                state = "raw"
                i += len(match.group(0))
                continue
        if char == '"':
            state = "string"
            i += 1
            continue
        if char == "'":
            # A lifetime such as 'a has no closing quote immediately after the name.
            if (nxt.isalpha() or nxt == "_") and not (
                i + 2 < len(text) and text[i + 2] == "'"
            ):
                i += 1
                continue
            state = "char"
            i += 1
            continue

        if char in "([{":
            stack.append((char, line))
        elif char in ")]}":
            if not stack or stack[-1][0] != pairs[char]:
                fail(f"{path.relative_to(ROOT)}:{line}: unmatched {char}")
            stack.pop()
        i += 1

    if state in {"string", "char", "raw", "block-comment"}:
        fail(f"{path.relative_to(ROOT)}: unterminated {state}")
    if stack:
        delimiter, opened = stack[-1]
        fail(f"{path.relative_to(ROOT)}:{opened}: unclosed {delimiter}")


def check_source_integrity() -> None:
    conflict = re.compile(r"^(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
    temporary_reference = re.compile(r"to_string\(\)\.as_str\(\)")
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in {".git", "target"} for part in path.parts):
            continue
        if path.suffix not in {".rs", ".toml", ".json", ".js", ".css", ".html", ".md", ".yml", ".yaml", ".sql"}:
            continue
        text = path.read_text(encoding="utf-8")
        if conflict.search(text):
            fail(f"merge-conflict marker in {path.relative_to(ROOT)}")
        if path.suffix == ".rs" and temporary_reference.search(text):
            fail(f"temporary string reference in {path.relative_to(ROOT)}")
        if "\x00" in text:
            fail(f"NUL byte in {path.relative_to(ROOT)}")


def check_javascript() -> str:
    node = shutil.which("node")
    if not node:
        return "not run (node unavailable)"
    subprocess.run(
        [node, "--check", str(ROOT / "web/app.js")],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return "passed"


def check_secret_hygiene() -> None:
    # Local installations legitimately contain .env and live databases. Check
    # export exclusion rather than breaking validation after the first run.
    from package import include
    forbidden = [ROOT / ".env", ROOT / "data/cyberwatch.db", ROOT / "secrets/admin-token",
                 ROOT / "backups/snapshot.db", ROOT / "client.key"]
    if any(include(path) for path in forbidden):
        fail("package policy includes a local secret or database")


def main() -> int:
    checks: list[tuple[str, str]] = []
    try:
        check_required()
        checks.append(("required files", "passed"))
        check_manifest()
        checks.append(("Cargo manifest", "passed"))
        check_json()
        checks.append(("JSON source catalogs", "passed"))
        check_schema()
        checks.append(("SQLite migration smoke test", "passed"))
        rust_files = check_rust_delimiters()
        checks.append(("Rust delimiter scan", f"passed ({rust_files} files)"))
        check_source_integrity()
        checks.append(("source integrity", "passed"))
        checks.append(("JavaScript syntax", check_javascript()))
        check_secret_hygiene()
        checks.append(("secret/data exclusion", "passed"))
    except Exception as error:  # noqa: BLE001
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        return 1

    print("Cyberwatch project validation")
    for name, result in checks:
        print(f"- {name}: {result}")
    cargo = shutil.which("cargo")
    print(f"- Rust compiler suite: {'available; run make check' if cargo else 'not run (cargo unavailable)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
