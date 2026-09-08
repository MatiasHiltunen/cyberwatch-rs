#!/usr/bin/env python3
"""Fail closed on the course's explicit deployment and workflow policies.

This small policy complements Trivy; it is not a Kubernetes schema validator.
Pass rendered manifests and --release to require immutable image digests.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workload_errors(document: dict, release: bool = False) -> list[str]:
    errors = []
    kind = document.get("kind")
    if kind not in {"Deployment", "Pod"}:
        return errors
    spec = document.get("spec", {})
    if kind == "Deployment":
        if spec.get("replicas") != 1:
            errors.append("SQLite deployment must have exactly one replica")
        if spec.get("strategy", {}).get("type") != "Recreate":
            errors.append("SQLite deployment must use Recreate")
        spec = spec.get("template", {}).get("spec", {})
    if spec.get("automountServiceAccountToken") is not False:
        errors.append("workload must disable automatic service-account credentials")
    if spec.get("hostNetwork") or spec.get("hostPID") or spec.get("hostIPC"):
        errors.append("host namespaces are forbidden")
    if any("hostPath" in volume for volume in spec.get("volumes", [])):
        errors.append("hostPath volumes are forbidden")
    security = spec.get("securityContext", {})
    if security.get("runAsNonRoot") is not True:
        errors.append("runAsNonRoot must be true")
    if security.get("seccompProfile", {}).get("type") != "RuntimeDefault":
        errors.append("RuntimeDefault seccomp profile is required")
    containers = spec.get("containers", []) + spec.get("initContainers", [])
    if not containers:
        errors.append("workload has no containers")
    for container in containers:
        security = container.get("securityContext", {})
        if security.get("privileged"):
            errors.append("privileged containers are forbidden")
        if security.get("allowPrivilegeEscalation") is not False:
            errors.append("privilege escalation must be disabled")
        if security.get("readOnlyRootFilesystem") is not True:
            errors.append("root filesystem must be read-only")
        caps = security.get("capabilities", {})
        if "ALL" not in caps.get("drop", []) or caps.get("add"):
            errors.append("all capabilities must be dropped without additions")
        for resource_type in ("requests", "limits"):
            resources = container.get("resources", {}).get(resource_type, {})
            if not resources.get("cpu") or not resources.get("memory"):
                errors.append(f"CPU and memory {resource_type} are required")
        if release and not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", container.get("image", "")):
            errors.append("release image must use a sha256 digest")
        if kind == "Deployment":
            for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
                if probe not in container:
                    errors.append(f"{probe} is required")
        for env in container.get("env", []):
            if re.search(r"TOKEN|PASSWORD|API_KEY", env.get("name", "")) and not env["name"].endswith("_FILE") and "value" in env:
                errors.append("inline secrets are forbidden")
    return errors


def workflow_errors(document: dict) -> list[str]:
    errors = []
    triggers = document.get("on", document.get(True, {})) or {}
    if "pull_request_target" in triggers:
        errors.append("pull_request_target is outside this repository's trust model")
    if document.get("permissions") != {"contents": "read"}:
        errors.append("workflow-level permission must be contents: read only")
    for job in document.get("jobs", {}).values():
        for step in job.get("steps", []):
            action = step.get("uses", "")
            if action and not action.startswith("./") and not re.fullmatch(r"[\w.-]+/[\w./-]+@[a-f0-9]{40}", action):
                errors.append(f"action must have a full commit pin: {action}")
            if action.startswith("actions/checkout@") and step.get("with", {}).get("persist-credentials") is not False:
                errors.append("checkout must not retain credentials")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    paths = args.paths or sorted((ROOT / "deploy/base").glob("*.yaml")) + sorted((ROOT / "deploy/maintenance/base").glob("*.yaml"))
    failures = []
    count = 0
    for path in paths:
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not isinstance(document, dict):
                continue
            count += 1
            failures.extend(f"{path}: {error}" for error in workload_errors(document, args.release))
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        failures.extend(f"{path}: {error}" for error in workflow_errors(yaml.safe_load(path.read_text(encoding="utf-8"))))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Deployment and workflow policy passed ({count} manifest documents; immutable image requirement: {args.release})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
