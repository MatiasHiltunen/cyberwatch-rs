#!/usr/bin/env python3
"""Export private host inventory or an online backup and verify the guest SHA-256.

Examples from the project root:
  python deploy/azure/export-evidence.py inventory --secrets-dir secrets/azure
  python deploy/azure/export-evidence.py backup --secrets-dir secrets/azure
"""
import argparse
import base64
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cyberwatch_azure_driver", Path(__file__).with_name("deploy.py"))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
PACKAGES = {"nginx", "nginx-common", "certbot", "openssl", "python3-cryptography"}


def load_state(path):
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    patterns = {"subscriptionId": r"[a-fA-F0-9-]{36}", "resourceGroup": r"[a-zA-Z0-9._-]{1,90}",
                "vmName": r"[a-zA-Z0-9._-]{1,64}", "storageAccount": r"[a-z0-9]{3,24}"}
    if not isinstance(state, dict) or any(not isinstance(state.get(key), str) or not re.fullmatch(pattern, state[key])
                                          for key, pattern in patterns.items()):
        raise RuntimeError("Deployment state has invalid subscription, resource group, VM, or storage identifiers")
    uuid.UUID(state["subscriptionId"])
    return state


def guest_script(kind, url, maximum):
    # Only fixed inventory paths or the backup helper's validated basename enter tar.
    if kind == "inventory":
        build = 'tar --dereference -czf "$archive" -C / etc/os-release etc/lsb-release var/lib/dpkg/status\n'
    else:
        build = r'''python3 /opt/cyberwatch/azure/backup-daily.py > "$work/backup-result.json"
backup=$(python3 - "$work/backup-result.json" <<'PY'
import json, pathlib, re, sys
result = json.loads(pathlib.Path(sys.argv[1]).read_text())
name = result.get('backup', '')
if result.get('status') != 'passed' or not re.fullmatch(r'cyberwatch-live-\d{8}T\d{6}Z\.db', name):
    raise RuntimeError('Backup helper did not return a verified snapshot')
for filename in (name, name[:-3] + '.json'):
    path = pathlib.Path('/var/backups/cyberwatch') / filename
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Backup export requires regular snapshot and report files')
print(name)
PY
)
tar -czf "$archive" -C /var/backups/cyberwatch "$backup" "${backup%.db}.json"
'''
    script = '''#!/bin/bash
set -euo pipefail
umask 077
work=$(mktemp -d /var/tmp/cyberwatch-export-XXXXXX)
trap 'rm -rf -- "$work"' EXIT
archive="$work/archive.tar.gz"
'''
    script += build
    script += '''python3 - "$archive" "$work" ''' + str(maximum) + ''' <<'PY'
import base64, hashlib, json, os, pathlib, subprocess, sys
archive, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
maximum = int(sys.argv[3])
size = archive.stat().st_size
if not 0 < size <= maximum:
    raise RuntimeError('Guest archive exceeds the configured export limit')
with archive.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
versions = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}\\t${Version}\\n',
    'nginx', 'nginx-common', 'certbot', 'openssl', 'python3-cryptography'], text=True)
result = {'archiveSha256': digest, 'archiveBytes': size, 'kernel': os.uname().release,
          'packages': dict(line.split('\\t', 1) for line in versions.splitlines())}
backup = work / 'backup-result.json'
if backup.exists():
    result['backup'] = json.loads(backup.read_text())
(work / 'guest-evidence.json').write_text(json.dumps(result))
PY
curl --fail --silent --show-error --retry 2 --max-time 600 --proto '=https' --tlsv1.2 -X PUT -H 'x-ms-blob-type: BlockBlob' --upload-file "$archive" ''' + shlex.quote(url) + '''
printf 'CYBERWATCH_EXPORT_META='
base64 -w0 "$work/guest-evidence.json"
printf '\\nCYBERWATCH_EXPORT_OK\\n'
'''
    return script


def parse_guest_evidence(messages, kind, maximum):
    matches = re.findall(r"(?m)^CYBERWATCH_EXPORT_META=([A-Za-z0-9+/=]+)\r?$", messages)
    if len(matches) != 1 or not re.search(r"(?m)^CYBERWATCH_EXPORT_OK\r?$", messages) or len(matches[0]) > 8192:
        raise RuntimeError("Guest did not return one complete export verification record; output withheld")
    evidence = json.loads(base64.b64decode(matches[0], validate=True))
    if (not isinstance(evidence, dict) or not re.fullmatch(r"[a-f0-9]{64}", evidence.get("archiveSha256", ""))
            or type(evidence.get("archiveBytes")) is not int or not 0 < evidence["archiveBytes"] <= maximum
            or not re.fullmatch(r"[A-Za-z0-9._+-]{1,200}", evidence.get("kernel", ""))):
        raise RuntimeError("Guest archive identity or size is invalid")
    packages = evidence.get("packages")
    if (not isinstance(packages, dict) or set(packages) != PACKAGES
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,200}", value)
                   for value in packages.values())):
        raise RuntimeError("Guest package-version evidence is incomplete or invalid")
    allowed = {"archiveSha256", "archiveBytes", "kernel", "packages"}
    if kind == "backup":
        backup = evidence.get("backup")
        if (not isinstance(backup, dict) or set(backup) != {"status", "backup", "bytes", "sha256", "retained"}
                or backup.get("status") != "passed" or type(backup.get("bytes")) is not int or backup["bytes"] <= 0
                or type(backup.get("retained")) is not int or not 1 <= backup["retained"] <= 7
                or not re.fullmatch(r"cyberwatch-live-\d{8}T\d{6}Z\.db", backup.get("backup", ""))
                or not re.fullmatch(r"[a-f0-9]{64}", backup.get("sha256", ""))):
            raise RuntimeError("Guest backup evidence is invalid")
        allowed.add("backup")
    if set(evidence) != allowed:
        raise RuntimeError("Guest evidence contains unexpected fields")
    return evidence


def export(kind, state, reports, secrets, maximum):
    azure = driver.azure_command()

    def az(*args):
        return json.loads(driver.command([*azure, *args, "--subscription", state["subscriptionId"],
                                          "--only-show-errors", "--output", "json"], sensitive=True))

    driver.secure_directory(secrets)
    reports.mkdir(parents=True, exist_ok=True)
    container = "evidence" if kind == "inventory" else "backups"
    now = dt.datetime.now(dt.timezone.utc)
    name = kind + "-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".tar.gz"
    az("storage", "container", "create", "--account-name", state["storageAccount"], "--name", container,
       "--auth-mode", "key", "--public-access", "off")
    expiry = (now + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")
    sas = az("storage", "blob", "generate-sas", "--account-name", state["storageAccount"], "--container-name", container,
             "--name", name, "--permissions", "cw", "--expiry", expiry, "--https-only", "--auth-mode", "key")
    if not isinstance(sas, str) or not sas or "\n" in sas or "\r" in sas:
        raise RuntimeError("Azure did not return a valid export SAS")
    url = "https://" + state["storageAccount"] + ".blob.core.windows.net/" + container + "/" + name + "?" + sas
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix="export-" + kind + "-",
                                     suffix=".sh", dir=secrets, delete=False) as stream:
        path = Path(stream.name)
        stream.write(guest_script(kind, url, maximum))
    try:
        result = az("vm", "run-command", "invoke", "--resource-group", state["resourceGroup"], "--name", state["vmName"],
                    "--command-id", "RunShellScript", "--scripts", "@" + str(path))
    finally:
        path.unlink(missing_ok=True)
    messages = "\n".join(item.get("message", "") for item in result.get("value", []))
    guest = parse_guest_evidence(messages, kind, maximum)
    blob_size = az("storage", "blob", "show", "--account-name", state["storageAccount"], "--container-name", container,
                   "--name", name, "--auth-mode", "key", "--query", "properties.contentLength")
    if type(blob_size) is not int or blob_size != guest["archiveBytes"]:
        raise RuntimeError("Uploaded blob size differs from the verified guest archive")
    with tempfile.TemporaryDirectory(prefix="export-verify-", dir=reports) as temporary:
        downloaded = Path(temporary) / name
        az("storage", "blob", "download", "--account-name", state["storageAccount"], "--container-name", container,
           "--name", name, "--file", str(downloaded), "--auth-mode", "key", "--no-progress")
        digest = driver.sha(downloaded)
        if downloaded.stat().st_size != guest["archiveBytes"] or digest != guest["archiveSha256"]:
            raise RuntimeError("Downloaded archive does not match the guest SHA-256 and size; export rejected")
        downloaded.replace(reports / name)
    record = {"kind": kind, "subscriptionId": state["subscriptionId"], "resourceGroup": state["resourceGroup"],
              "vmName": state["vmName"], "storageAccount": state["storageAccount"], "container": container,
              "blob": name, "downloaded": name, "bytes": guest["archiveBytes"], "sha256": digest,
              "guestSha256": guest["archiveSha256"], "exportedAt": now.isoformat(), "status": "passed", "guestEvidence": guest}
    driver.write_json(reports / (kind + "-export.json"), record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=["inventory", "backup"])
    parser.add_argument("--deployment-file", "--deployment", type=Path, default=ROOT / "reports/azure/deployment.json")
    parser.add_argument("--secrets-dir", type=Path, default=ROOT / "secrets/azure")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/azure")
    parser.add_argument("--max-bytes", type=int, default=512 * 1024 * 1024)
    options = parser.parse_args(argv)
    if options.max_bytes <= 0:
        parser.error("--max-bytes must be positive")
    state = load_state(options.deployment_file)
    record = export(options.kind, state, options.output_dir.resolve(), options.secrets_dir.resolve(), options.max_bytes)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit("Evidence export failed; no successful record was written for this attempt and sensitive output was withheld.") from None
