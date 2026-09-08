#!/usr/bin/env python3
"""Inspect the actual production image and export only its runnable payload.

The OCI root filesystem is read as a tar stream; no image-provided code is run
and no archive paths are extracted onto the host. Size limits are CI gates.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {
    "usr/local/bin/cyberwatch-rs": "cyberwatch-rs",
    "app/web/index.html": "web/index.html",
    "app/web/app.js": "web/app.js",
    "app/web/styles.css": "web/styles.css",
    "app/LICENSE": "LICENSE",
}
FORBIDDEN = re.compile(
    r"(^|/)(?:s?bin/(?:sh|bash|dash|curl|tar|apt|apt-get|cargo|rustc|python[0-9.]*)$"
    r"|(?:src|target|node_modules|\.git|\.devcontainer)/|(?:lib|lib64)/python[0-9.]+/)"
)


def read_payload(rootfs: Path, architecture: str, limits: dict) -> dict[str, bytes]:
    payload = {}
    with tarfile.open(rootfs, "r:") as source:
        for member in source:
            path = member.name.removeprefix("./")
            if FORBIDDEN.search(path) or path.startswith(("app/tools/", "root/.cargo/", "usr/local/cargo/")):
                raise ValueError(f"production image contains development/maintenance content: {path}")
            if path not in PAYLOAD:
                continue
            if path in payload or not member.isfile():
                raise ValueError(f"payload must contain one regular file at {path}")
            maximum = limits["binary_max_bytes"] if path.endswith("/cyberwatch-rs") else 1024 * 1024
            if member.size > maximum:
                raise ValueError(f"payload exceeds size limit: {path} ({member.size} bytes, limit {maximum})")
            handle = source.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot read {path}")
            payload[path] = handle.read(maximum + 1)
    if set(payload) != set(PAYLOAD):
        raise ValueError("image is missing runtime files: " + ", ".join(sorted(set(PAYLOAD) - set(payload))))
    binary = payload["usr/local/bin/cyberwatch-rs"]
    expected_machine = {"amd64": 62, "arm64": 183}.get(architecture)
    if expected_machine is None or len(binary) < 20 or binary[:6] != b"\x7fELF\x02\x01" or int.from_bytes(binary[18:20], "little") != expected_machine:
        raise ValueError("runtime executable does not match the image's Linux ELF architecture")
    return payload


def write_bundle(payload: dict[str, bytes], output: Path):
    with output.open("wb") as destination:
        with gzip.GzipFile(filename="", mode="wb", fileobj=destination, compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for source, relative in sorted(PAYLOAD.items(), key=lambda item: item[1]):
                    data = payload[source]
                    member = tarfile.TarInfo("cyberwatch-rs/" + relative)
                    member.size = len(data)
                    member.mode = 0o755 if relative == "cyberwatch-rs" else 0o644
                    member.mtime = 0
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    archive.addfile(member, io.BytesIO(data))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--policy", type=Path, default=ROOT / "tools/runtime_size_policy.json")
    args = parser.parse_args()
    limits = json.loads(args.policy.read_text(encoding="utf-8"))
    for key in ("image_max_bytes", "rootfs_tar_max_bytes", "binary_max_bytes", "archive_max_bytes"):
        if type(limits.get(key)) is not int or limits[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image], text=True))[0]
    if info["Os"] != "linux" or info["Architecture"] not in {"amd64", "arm64"}:
        raise ValueError("runtime archives support Linux amd64 and arm64 images")
    if info["Size"] > limits["image_max_bytes"]:
        raise ValueError(f"image is {info['Size']} bytes; limit is {limits['image_max_bytes']}")
    architecture = info["Architecture"]
    with tempfile.TemporaryDirectory(prefix="cyberwatch-runtime-") as temporary:
        rootfs = Path(temporary) / "rootfs.tar"
        container = subprocess.check_output(["docker", "create", info["Id"]], text=True).strip()
        try:
            subprocess.run(["docker", "export", "--output", str(rootfs), container], check=True)
            rootfs_bytes = rootfs.stat().st_size
            if rootfs_bytes > limits["rootfs_tar_max_bytes"]:
                raise ValueError(f"exported root filesystem is {rootfs_bytes} bytes; limit is {limits['rootfs_tar_max_bytes']}")
            payload = read_payload(rootfs, architecture, limits)
        finally:
            subprocess.run(["docker", "rm", "--volumes", container], check=True, stdout=subprocess.DEVNULL)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive = args.output_dir / f"cyberwatch-rs-linux-{architecture}.tar.gz"
    digest = write_bundle(payload, archive)
    report = {
        "image_id": info["Id"], "platform": "linux/" + architecture,
        "image_bytes": info["Size"], "binary_bytes": len(payload["usr/local/bin/cyberwatch-rs"]),
        "rootfs_tar_bytes": rootfs_bytes,
        "size_semantics": "image_bytes is Docker's engine-dependent Size; rootfs_tar_bytes is the uncompressed exported filesystem including tar metadata",
        "runtime_archive_bytes": archive.stat().st_size, "runtime_archive_sha256": digest,
        "runtime_files": sorted(PAYLOAD.values()), "limits": limits,
        "status": "passed" if archive.stat().st_size <= limits["archive_max_bytes"] else "failed",
    }
    (args.output_dir / "runtime-size.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "passed":
        raise ValueError("compressed runtime archive exceeds its size limit")


if __name__ == "__main__":
    main()
