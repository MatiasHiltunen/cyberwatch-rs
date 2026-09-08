#!/usr/bin/env python3
"""Promote an attested digest into one pre-provisioned namespace; recover on failure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time


def validate_inputs(image: str, namespace: str, repository: str):
    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_./-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("image must be a GHCR image with a full lowercase sha256 digest")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", namespace) or not namespace.startswith("cyberwatch-"):
        raise ValueError("use a dedicated cyberwatch-* namespace")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be OWNER/REPOSITORY")
    if not image.startswith("ghcr.io/" + repository.lower() + "@"):
        raise ValueError("image must belong to the expected source repository")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/deployment.json"))
    args = parser.parse_args()
    validate_inputs(args.image, args.namespace, args.repository)
    # Verify before touching the cluster. A registry tag alone is not evidence.
    subprocess.run(["gh", "attestation", "verify", "oci://" + args.image, "--repo", args.repository,
                    "--signer-workflow", args.repository + "/.github/workflows/release.yml",
                    "--source-ref", "refs/heads/main", "--deny-self-hosted-runners"], check=True, timeout=120)
    prefix = ["kubectl", "--request-timeout=30s", "--namespace", args.namespace]
    deployment = json.loads(subprocess.check_output(prefix + ["get", "deployment", "cyberwatch", "-o", "json"], text=True, timeout=45))
    if deployment["spec"].get("replicas") != 1 or deployment["spec"].get("strategy", {}).get("type") != "Recreate":
        raise RuntimeError("refusing to change a deployment that violates SQLite single-writer policy")
    containers = deployment["spec"]["template"]["spec"]["containers"]
    previous = next(container["image"] for container in containers if container["name"] == "cyberwatch")
    validate_inputs(previous, args.namespace, args.repository)
    # A known healthy starting state is needed to claim successful recovery.
    subprocess.run(prefix + ["rollout", "status", "deployment/cyberwatch", "--timeout=120s"], check=True, timeout=150)
    started = time.monotonic()
    report = {"image": args.image, "previous_image": previous, "status": "started", "rollback": "not-needed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(prefix + ["set", "image", "deployment/cyberwatch", "cyberwatch=" + args.image], check=True, timeout=45)
        subprocess.run(prefix + ["rollout", "status", "deployment/cyberwatch", "--timeout=180s"], check=True, timeout=210)
        report["status"] = "deployed"
    except (subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        report["rollback"] = "failed"
        subprocess.run(prefix + ["set", "image", "deployment/cyberwatch", "cyberwatch=" + previous], check=True, timeout=45)
        subprocess.run(prefix + ["rollout", "status", "deployment/cyberwatch", "--timeout=180s"], check=True, timeout=210)
        report["rollback"] = "restored-previous-image"
        raise
    finally:
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
