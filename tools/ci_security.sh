#!/usr/bin/env bash
# The existing GitHub workflow uses the same reviewed Trivy version and severity gate.
set -euo pipefail
version=0.74.0
mkdir -p reports
tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT
archive="trivy_${version}_Linux-64bit.tar.gz"
base="https://github.com/aquasecurity/trivy/releases/download/v${version}"
curl --fail --silent --show-error --location "$base/$archive" -o "$tool_dir/$archive"
curl --fail --silent --show-error --location "$base/trivy_${version}_checksums.txt" -o "$tool_dir/checksums.txt"
(cd "$tool_dir" && grep "  ${archive}$" checksums.txt | sha256sum --check --strict)
tar -xzf "$tool_dir/$archive" -C "$tool_dir" trivy
if [[ ${1:-} == source ]]; then
    "$tool_dir/trivy" fs --scanners vuln,secret,misconfig --skip-dirs target,.git,.ci-venv,.sast-venv,reports,secrets --severity HIGH,CRITICAL --exit-code 1 --format json --output reports/repository-security.json .
elif [[ ${1:-} == image && $# == 2 ]]; then
    "$tool_dir/trivy" image --format cyclonedx --output reports/image-sbom.cdx.json "$2"
    "$tool_dir/trivy" image --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 --format json --output reports/image-security.json "$2"
else
    echo 'Use source or image IMAGE' >&2
    exit 2
fi
