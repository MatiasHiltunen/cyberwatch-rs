#!/usr/bin/env python3
"""Deploy the single-instance Azure lab through az; never print application secrets."""
import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SUBSCRIPTION = "afe8ae0d-d866-47a9-bc56-e1f4475e6cc6"
PROXY_STRATEGY = "ubuntu-nginx-certbot"

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError("Refusing to overwrite a symlink with deployment data")
    # An interrupted write must not destroy the last deployment or credential file.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def command(args, *, input_data=None, sensitive=False, timeout=None):
    try:
        result = subprocess.run([str(a) for a in args], input=input_data, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{Path(str(args[0])).name} timed out after {timeout} seconds; output withheld") from None
    if result.returncode:
        if sensitive:
            raise RuntimeError(f"{Path(str(args[0])).name} failed; sensitive output withheld")
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-6000:])
    return result.stdout.decode("utf-8-sig", errors="strict").strip()

def az(*args, sensitive=False):
    return command([*AZ, *args, "--subscription", opts.subscription_id, "--only-show-errors", "--output", "json"], sensitive=sensitive)

def az_json(*args, sensitive=False):
    return json.loads(az(*args, sensitive=sensitive))

def secure_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        principal = command(["whoami"])
        command(["icacls", str(path), "/inheritance:r", "/grant:r", principal + ":(OI)(CI)F"])
    else:
        path.chmod(0o700)

def openssl():
    found = shutil.which("openssl")
    fallback = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
    if found:
        return found
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("OpenSSL is required for locally encrypted credential transfer")

def azure_command():
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required")
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # The official MSI az.cmd invokes this interpreter. Calling it directly
        # preserves argv, including @JSON paths, spaces, parentheses, and tag text.
        interpreter = Path(executable).resolve().parent.parent / "python.exe"
        if not interpreter.is_file():
            raise RuntimeError("Azure CLI batch shim has no bundled Python interpreter")
        return [str(interpreter), "-IBm", "azure.cli"]
    return [executable]

def organization_tags(account):
    owner = account.get("user", {}).get("name")
    if not isinstance(owner, str) or not owner.strip():
        raise RuntimeError("Signed-in Azure identity is required for the Owner tag")
    # Values audited against the subscription's existing organizational tags.
    # GDPR is the required organizational metadata category, not a compliance claim.
    tags = {"CostCentre": "4257100", "Owner": owner, "Ownerteam": "TVT",
            "Servicename": "Cyberwatch-YAMK", "Servicestage": "SANDBOX", "GDPR": "1",
            "Description": "Live public-source cyber intelligence course example"}
    if opts.org_tags:
        supplied = json.loads(opts.org_tags.read_text(encoding="utf-8-sig"))
        if not isinstance(supplied, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                or not key or not value for key, value in supplied.items()):
            raise RuntimeError("Organization tags must be a JSON object of non-empty string values")
        tags.update(supplied)
    tags.update(project="Cyberwatch", course="YAMK282-YAMK283", environment="student")
    return tags

def prepare():
    account = az_json("account", "show")
    if account["id"] != opts.subscription_id or account["state"] != "Enabled":
        raise RuntimeError("Requested subscription is not enabled")
    tags = organization_tags(account)
    secure_directory(SECRETS)
    private = SECRETS / "operator-key.pem"
    if not private.exists():
        command([openssl(), "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", private], sensitive=True)
        if os.name != "nt":
            private.chmod(0o600)
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise RuntimeError("ssh-keygen is required to serialize the VM public key")
    public = command([keygen, "-y", "-f", private], sensitive=True)
    (SECRETS / "operator-key.pub").write_text(public + "\n", encoding="ascii")
    command([openssl(), "pkey", "-in", private, "-pubout", "-out", SECRETS / "transfer-public.pem"], sensitive=True)
    parameters = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#", "contentVersion": "1.0.0.0",
                  "parameters": {"adminSshPublicKey": {"value": public}, "cloudInit": {"value": (HERE / "cloud-init.yaml").read_text()},
                  "location": {"value": opts.location}, "namePrefix": {"value": opts.name_prefix}, "dnsLabel": {"value": opts.dns_label}}}
    write_json(REPORTS / "parameters.json", parameters)
    exists = az_json("group", "exists", "--name", opts.resource_group)
    if exists:
        group = az_json("group", "show", "--name", opts.resource_group)
        if (group.get("tags") or {}).get("project") != "Cyberwatch":
            raise RuntimeError("Existing resource group is not tagged as this Cyberwatch deployment")
    else:
        az("group", "create", "--name", opts.resource_group, "--location", opts.location,
           "--tags", *(key + "=" + value for key, value in tags.items()))
    return ["--resource-group", opts.resource_group, "--template-file", str(HERE / "main.bicep"), "--parameters", "@" + str(REPORTS / "parameters.json")]

def infrastructure(what_if):
    arguments = prepare()
    if what_if:
        report = az_json("deployment", "group", "what-if", *arguments, "--no-pretty-print")
        write_json(REPORTS / "what-if.json", report)
        print(json.dumps({"status": report.get("status"), "changes": [{"type": c["changeType"], "resource": c["resourceId"]} for c in report.get("changes", [])]}, indent=2))
    else:
        report = az_json("deployment", "group", "create", "--name", "cyberwatch-infrastructure", *arguments)
        outputs = {key: value["value"] for key, value in report["properties"]["outputs"].items()}
        outputs.update(subscriptionId=opts.subscription_id, resourceGroup=opts.resource_group, location=opts.location)
        write_json(REPORTS / "deployment.json", outputs)
        print(json.dumps(outputs, indent=2))

def inspect_image_archive(path, image, expected_config_id=None):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Image archive must be a regular Docker save tar file")
    with tarfile.open(path) as archive:
        def read_json_bytes(name, maximum):
            member = archive.getmember(name)
            if not member.isfile() or not 0 < member.size <= maximum:
                raise RuntimeError("Docker save metadata must be a bounded regular file")
            return archive.extractfile(member).read()

        manifest = json.loads(read_json_bytes("manifest.json", 1024 * 1024))
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise RuntimeError("Export must contain exactly one production image")
        tags = manifest[0].get("RepoTags") or []
        if expected_config_id is not None and tags != [image]:
            raise RuntimeError("Provided Docker save archive must contain exactly the requested image tag")
        config_bytes = read_json_bytes(manifest[0]["Config"], 4 * 1024 * 1024)
        config = json.loads(config_bytes)
        if config.get("architecture") != "arm64" or config.get("os") != "linux":
            raise RuntimeError("This deployment requires the verified Linux ARM64 production image")
        # Newer Docker stores may report an OCI index as .Id. Pin the saved image's
        # configuration digest, which identifies the runnable image after load.
        config_id = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
        if expected_config_id is not None and config_id != expected_config_id:
            raise RuntimeError("Provided image archive does not match the required configuration SHA-256")
        return config_id, image if image in tags else config_id


def build_bundle():
    required = [HERE / name for name in ("install-runtime.sh", "prepare-data-disk.py", "configure-runtime.py",
                                         "backup-daily.py", "check-health.sh", "check-persistence.py", "maintain-kernel.py", "restore-runtime.py", "compose.yaml", "nginx-http.conf.template",
                                         "nginx-https.conf.template")]
    required.append(ROOT / "tools/backup.py")
    if any(path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()) for path in required):
        raise RuntimeError("Runtime bundle inputs are incomplete or contain links outside the project")
    # Fresh staging avoids retaining obsolete scripts or files from previous runs.
    with tempfile.TemporaryDirectory(prefix="bundle-", dir=REPORTS) as temporary:
        temporary = Path(temporary)
        stage = temporary / "payload"
        (stage / "images").mkdir(parents=True)
        if opts.image_archive:
            image_tar = opts.image_archive.absolute()
        else:
            image_tar = temporary / "cyberwatch-production.tar"
            # Bound only the local Docker export; Azure operations keep their
            # existing long-running behavior for provisioning and Run Command.
            command(["docker", "image", "save", "--output", image_tar, opts.image], timeout=300)
        config_id, image_reference = inspect_image_archive(image_tar, opts.image, opts.image_config_id)
        with image_tar.open("rb") as source, (stage / "images/cyberwatch-production.tar.gz").open("wb") as output:
            with gzip.GzipFile(filename="", fileobj=output, mode="wb", compresslevel=9, mtime=0) as target:
                shutil.copyfileobj(source, target)
        for path in required:
            destination = stage / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        payload = sorted(path for path in stage.rglob("*") if path.is_file())
        (stage / "SHA256SUMS").write_text("".join(sha(path) + "  " + path.relative_to(stage).as_posix() + "\n" for path in payload), encoding="ascii")
        bundle = temporary / "cyberwatch-azure-bundle.tar.gz"
        with bundle.open("wb") as output, gzip.GzipFile(filename="", fileobj=output, mode="wb", compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for path in payload + [stage / "SHA256SUMS"]:
                    entry = tarfile.TarInfo(path.relative_to(stage).as_posix())
                    entry.size = path.stat().st_size
                    entry.mode = 0o644
                    with path.open("rb") as source:
                        archive.addfile(entry, source)
        release = {"bundle": "cyberwatch-azure-bundle.tar.gz", "sha256": sha(bundle), "bytes": bundle.stat().st_size,
                   "image": image_reference, "sourceImage": opts.image, "imageConfigId": config_id,
                   "proxyStrategy": PROXY_STRATEGY, "platform": "linux/arm64",
                   "imageSource": "provided-archive" if opts.image_archive else "docker-export",
                   "imageArchiveSha256": sha(image_tar)}
        bundle.replace(REPORTS / release["bundle"])
    write_json(REPORTS / "release.json", release)
    print(json.dumps(release, indent=2))

def deployment_state():
    deployment = json.loads((REPORTS / "deployment.json").read_text(encoding="utf-8-sig"))
    expected = {"subscriptionId": opts.subscription_id, "resourceGroup": opts.resource_group,
                "location": opts.location, "vmName": opts.name_prefix}
    if any(deployment.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Saved deployment does not match the requested subscription, resource group, region, and VM")
    expected_fqdn = opts.dns_label + "." + opts.location + ".cloudapp.azure.com"
    if deployment.get("fqdn") != expected_fqdn or not re.fullmatch(r"[a-z0-9]{3,24}", deployment.get("storageAccount", "")):
        raise RuntimeError("Saved deployment endpoint or storage account is invalid")
    if deployment.get("container") != "artifacts":
        raise RuntimeError("Deployment uploads must target the artifacts container")
    return deployment

def release_state():
    release = json.loads((REPORTS / "release.json").read_text(encoding="utf-8-sig"))
    if (release.get("bundle") != "cyberwatch-azure-bundle.tar.gz" or release.get("platform") != "linux/arm64"
            or not re.fullmatch(r"[a-f0-9]{64}", release.get("sha256", ""))
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", release.get("imageConfigId", ""))
            or not re.fullmatch(r"[a-z0-9][a-z0-9._/:@-]+", release.get("image", ""))
            or release.get("proxyStrategy") != PROXY_STRATEGY or "caddyImage" in release):
        raise RuntimeError("Saved release metadata is invalid or belongs to another platform/proxy strategy")
    bundle = REPORTS / release["bundle"]
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size != release.get("bytes") or sha(bundle) != release["sha256"]:
        raise RuntimeError("Deployment bundle does not match the saved size and SHA-256")
    return release

def run_script(script, filename="run-command.sh", sensitive=False):
    path = (SECRETS if sensitive else REPORTS) / filename
    path.write_text(script, encoding="utf-8", newline="\n")
    try:
        report = az_json("vm", "run-command", "invoke", "--resource-group", opts.resource_group,
                         "--name", opts.name_prefix, "--command-id", "RunShellScript", "--scripts", "@" + str(path), sensitive=sensitive)
    finally:
        if sensitive:
            path.unlink(missing_ok=True)
    messages = "\n".join(entry.get("message", "") for entry in report.get("value", []))
    if not sensitive:
        write_json(REPORTS / (filename + ".result.json"), report)
    return messages

def install():
    secure_directory(SECRETS)
    deployment = deployment_state()
    release = release_state()
    blob = "releases/" + release["sha256"] + ".tar.gz"
    az("storage", "blob", "upload", "--account-name", deployment["storageAccount"], "--container-name", deployment["container"],
       "--name", blob, "--file", str(REPORTS / release["bundle"]), "--auth-mode", "key", "--overwrite", "true")
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%MZ")
    sas = az_json("storage", "blob", "generate-sas", "--account-name", deployment["storageAccount"], "--container-name", deployment["container"],
                  "--name", blob, "--permissions", "r", "--expiry", expiry, "--https-only", "--auth-mode", "key", sensitive=True)
    url = "https://" + deployment["storageAccount"] + ".blob.core.windows.net/" + deployment["container"] + "/" + blob + "?" + sas
    directory = "/opt/cyberwatch/releases/" + release["sha256"]
    script = f"""#!/bin/bash
set -euo pipefail
umask 077
timeout 600 cloud-init status --wait > /var/log/cyberwatch-cloud-init-wait.log 2>&1
install -d -m 700 '{directory}'
curl --fail --silent --show-error --retry 3 --proto '=https' --tlsv1.2 '{url}' --output '{directory}/bundle.tar.gz'
printf '%s  %s\\n' '{release['sha256']}' '{directory}/bundle.tar.gz' | sha256sum --check --status
tar -xzf '{directory}/bundle.tar.gz' -C '{directory}' --no-same-owner
cd '{directory}'
bash deploy/azure/install-runtime.sh --bundle-dir '{directory}' --fqdn '{deployment['fqdn']}' --image '{release['image']}' --image-id '{release['imageConfigId']}'
echo CYBERWATCH_INSTALL_OK
"""
    output = run_script(script, "install-with-expiring-sas.sh", sensitive=True)
    if "CYBERWATCH_INSTALL_OK" not in output:
        (SECRETS / "install-diagnostic.txt").write_text(output, encoding="utf-8")
        raise RuntimeError("VM installer did not report success; diagnostic saved in excluded secrets directory")
    write_json(REPORTS / "install.json", {"status": "passed", "bundleSha256": release["sha256"], "vm": deployment["vmName"], "fqdn": deployment["fqdn"]})
    print("VM runtime installed; application secrets were not printed.")

def credentials():
    secure_directory(SECRETS)
    deployment = deployment_state()
    private = SECRETS / "operator-key.pem"
    if private.is_symlink() or not private.is_file():
        raise RuntimeError("The original local operator private key is required for encrypted credential transfer")
    # Derive the transfer public key from the private key used for decryption;
    # never trust a stale or replaced public-key sidecar on subsequent runs.
    public_pem = command([openssl(), "pkey", "-in", private, "-pubout"], sensitive=True) + "\n"
    public = base64.b64encode(public_pem.encode("ascii")).decode("ascii")
    script = f"""#!/bin/bash
set -euo pipefail
umask 077
key=$(mktemp)
trap 'rm -f "$key"' EXIT
printf '%s' '{public}' | base64 -d > "$key"
printf 'ENCRYPTED_ACCESS='
python3 -c 'import json,pathlib; p=pathlib.Path("/etc/cyberwatch/secrets"); print(json.dumps({{"readerUsername":"cyberwatch","readerPassword":(p/"reader-password").read_text().strip(),"adminToken":(p/"admin-token").read_text().strip()}}))' | openssl pkeyutl -encrypt -pubin -inkey "$key" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256 | base64 -w0
printf '\\n'
"""
    output = run_script(script, "encrypted-access.sh", sensitive=True)
    match = re.search(r"ENCRYPTED_ACCESS=([A-Za-z0-9+/=]+)", output)
    if not match:
        raise RuntimeError("Encrypted credential response missing; no plaintext response requested")
    ciphertext = SECRETS / "access.encrypted"
    ciphertext.write_bytes(base64.b64decode(match[1], validate=True))
    plaintext = command([openssl(), "pkeyutl", "-decrypt", "-inkey", SECRETS / "operator-key.pem", "-in", ciphertext,
                         "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                         "-pkeyopt", "rsa_mgf1_md:sha256"], sensitive=True)
    data = json.loads(plaintext)
    if (not isinstance(data, dict) or set(data) != {"readerUsername", "readerPassword", "adminToken"}
            or data["readerUsername"] != "cyberwatch"
            or any(not isinstance(data[key], str) or not 32 <= len(data[key]) <= 200
                   or not data[key].isprintable() for key in ("readerPassword", "adminToken"))):
        raise RuntimeError("Decrypted credential response has an unexpected format")
    data["url"] = "https://" + deployment["fqdn"]
    write_json(SECRETS / "access.json", data)
    print("Credentials saved privately at " + str(SECRETS / "access.json"))

def main(argv=None):
    global opts, AZ, REPORTS, SECRETS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["what-if", "infra", "bundle", "install", "credentials"],
                        help="what-if may create the empty tagged resource group; infra provisions resources; bundle is local; install and credentials target the saved deployment")
    parser.add_argument("--subscription-id", default=SUBSCRIPTION)
    parser.add_argument("--resource-group", default="rg-cyberwatch-yamk-swe")
    parser.add_argument("--location", default="swedencentral")
    parser.add_argument("--name-prefix", default="cyberwatch-yamk")
    parser.add_argument("--dns-label", default="cyberwatch-yamk-afe8ae-20260908")
    parser.add_argument("--image", default="cyberwatch-size-optimized:local")
    parser.add_argument("--image-archive", type=Path, help="Bundle only: reuse a Docker save tar without contacting Docker")
    parser.add_argument("--image-config-id", help="Required with --image-archive: exact sha256:<64 lowercase hex> image configuration digest")
    parser.add_argument("--secrets-dir", type=Path, default=ROOT / "secrets/azure")
    parser.add_argument("--org-tags", type=Path, help="Optional JSON object overriding audited organization resource-group tags")
    opts = parser.parse_args(argv)
    for value in [opts.subscription_id, opts.resource_group, opts.name_prefix, opts.dns_label, opts.location]:
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", value):
            parser.error("Identifiers must contain only letters, numbers, dots, hyphens and underscores")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._/:@-]+", opts.image):
        parser.error("Image must be a lowercase Docker image reference")
    if opts.image_archive or opts.image_config_id:
        if opts.action != "bundle":
            parser.error("--image-archive and --image-config-id apply only to the bundle action")
        if not opts.image_archive or not opts.image_config_id:
            parser.error("--image-archive and --image-config-id must be provided together")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", opts.image_config_id):
            parser.error("--image-config-id must be a canonical SHA-256 configuration digest")
    AZ = azure_command() if opts.action != "bundle" else None
    REPORTS = ROOT / "reports/azure"
    REPORTS.mkdir(parents=True, exist_ok=True)
    SECRETS = opts.secrets_dir.resolve()
    if opts.action in {"what-if", "infra"}:
        infrastructure(opts.action == "what-if")
    elif opts.action == "bundle":
        build_bundle()
    elif opts.action == "install":
        install()
    else:
        credentials()


if __name__ == "__main__":
    os.umask(0o077)
    main()
