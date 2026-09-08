#!/usr/bin/env bash
# Run after cloud-init, from a checksum-verified deployment bundle. No secrets in args.
set -euo pipefail
umask 077
bundle_dir='' fqdn='' image='' image_id=''
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle-dir) bundle_dir="$2"; shift 2 ;;
        --fqdn) fqdn="$2"; shift 2 ;;
        --image) image="$2"; shift 2 ;;
        --image-id) image_id="$2"; shift 2 ;;
        *) printf 'Unsupported installer argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
[[ $(id -u) == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ "$bundle_dir" == /* && -d "$bundle_dir" ]] || { echo 'An absolute bundle directory is required.' >&2; exit 1; }
[[ "$fqdn" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$fqdn" == *.* && "$fqdn" != *..* ]] || { echo 'Invalid public FQDN.' >&2; exit 1; }
[[ "$image" =~ ^[a-z0-9][a-z0-9._/:@-]+$ ]] || { echo 'Invalid production image tag.' >&2; exit 1; }
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Expected immutable image configuration digest.' >&2; exit 1; }
cd -- "$bundle_dir"
python3 - "$bundle_dir" <<'PY'
import hashlib
from pathlib import Path
import re
import sys
root = Path(sys.argv[1]).resolve(strict=True)
required = {'images/cyberwatch-production.tar.gz', 'tools/backup.py',
            'deploy/azure/install-runtime.sh', 'deploy/azure/prepare-data-disk.py',
            'deploy/azure/configure-runtime.py', 'deploy/azure/backup-daily.py',
            'deploy/azure/check-health.sh', 'deploy/azure/restore-runtime.py',
            'deploy/azure/check-persistence.py',
            'deploy/azure/maintain-kernel.py',
            'deploy/azure/nginx-http.conf.template', 'deploy/azure/nginx-https.conf.template',
            'deploy/azure/compose.yaml'}
seen = set()
for line in (root / 'SHA256SUMS').read_text().splitlines():
    match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
    if not match:
        raise RuntimeError('Invalid checksum manifest')
    digest, name = match.groups()
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or name in seen:
        raise RuntimeError('Unsafe or duplicate checksum path')
    candidate = root / path
    if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        raise RuntimeError('Checksum payload must be a regular in-bundle file')
    actual = hashlib.file_digest(candidate.open('rb'), 'sha256').hexdigest()
    if actual != digest:
        raise RuntimeError(f'Checksum mismatch: {name}')
    seen.add(name)
if not required <= seen:
    raise RuntimeError('Missing required checksummed deployment files')
print('Deployment payload checksums verified.')
PY
for name in cyberwatch; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        label=$(docker container inspect --format '{{index .Config.Labels "io.cyberwatch.managed"}}' "$name")
        [[ "$label" == azure-live ]] || { echo 'Refusing to replace an unmanaged container.' >&2; exit 1; }
    fi
done
python3 deploy/azure/prepare-data-disk.py
install -d -m 0755 /opt/cyberwatch /opt/cyberwatch/tools /opt/cyberwatch/azure
install -d -m 0700 /etc/cyberwatch /var/backups/cyberwatch
install -m 0644 tools/backup.py /opt/cyberwatch/tools/backup.py
for name in configure-runtime.py backup-daily.py check-health.sh restore-runtime.py check-persistence.py maintain-kernel.py compose.yaml nginx-http.conf.template nginx-https.conf.template; do
    install -m 0644 "deploy/azure/$name" "/opt/cyberwatch/azure/$name"
done
python3 - "$image" "$image_id" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import tarfile
with tarfile.open('images/cyberwatch-production.tar.gz', 'r:gz') as archive:
    manifest_member = archive.getmember('manifest.json')
    if not manifest_member.isfile() or manifest_member.size > 1024 * 1024:
        raise RuntimeError('Invalid Docker-save manifest')
    manifest = json.load(archive.extractfile(manifest_member))
    if len(manifest) != 1 or manifest[0].get('RepoTags') != [sys.argv[1]]:
        raise RuntimeError('Docker archive must contain exactly the reviewed single image/tag')
    member = archive.getmember(manifest[0]['Config'])
    if not member.isfile() or member.size > 1024 * 1024:
        raise RuntimeError('Invalid image configuration payload')
    encoded = archive.extractfile(member).read()
    if 'sha256:' + hashlib.sha256(encoded).hexdigest() != sys.argv[2]:
        raise RuntimeError('Archive image configuration digest does not match review')
    config = json.loads(encoded)
    if config.get('os') != 'linux' or config.get('architecture') != 'arm64':
        raise RuntimeError('Archive must contain the reviewed Linux ARM64 image')
    Path('/opt/cyberwatch/azure/image-config.json').write_text(json.dumps(config))
print('Canonical image configuration digest and platform verified before loading.')
PY
gzip -dc images/cyberwatch-production.tar.gz | docker load >/dev/null
actual_id=$(python3 - "$image" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
expected = json.loads(Path('/opt/cyberwatch/azure/image-config.json').read_text())
actual = json.loads(subprocess.check_output(['docker', 'image', 'inspect', sys.argv[1]]))[0]
if actual['Os'] != 'linux' or actual['Architecture'] != 'arm64':
    raise RuntimeError('Loaded image platform differs from the verified archive')
if actual['Config'] != expected['config'] or actual['RootFS']['Layers'] != expected['rootfs']['diff_ids']:
    raise RuntimeError('Loaded image runtime configuration or filesystem layers differ from review')
print(actual['Id'])
PY
)
# Ubuntu's security-maintained packages avoid an additional proxy container image.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y >/dev/null
apt-get install -y --no-install-recommends nginx certbot >/dev/null
python3 /opt/cyberwatch/azure/configure-runtime.py "$fqdn" "$actual_id"
install -d -m 0755 /var/lib/letsencrypt /etc/letsencrypt/renewal-hooks/deploy
install -d -o root -g www-data -m 0750 /etc/nginx/cyberwatch
{
    printf 'cyberwatch:'
    openssl passwd -6 -stdin < /etc/cyberwatch/secrets/reader-password
} > /etc/nginx/cyberwatch/reader.htpasswd
chown root:www-data /etc/nginx/cyberwatch/reader.htpasswd
chmod 0640 /etc/nginx/cyberwatch/reader.htpasswd
install -d -m 0755 /etc/systemd/system/nginx.service.d
cat > /etc/systemd/system/nginx.service.d/cyberwatch-limits.conf <<'UNIT'
[Service]
MemoryMax=128M
CPUQuota=50%
TasksMax=64
UNIT
cat > /etc/letsencrypt/renewal-hooks/deploy/cyberwatch-nginx.sh <<'HOOK'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
HOOK
chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/cyberwatch-nginx.sh
if [[ -L /etc/nginx/sites-enabled/default && $(readlink -f /etc/nginx/sites-enabled/default) == /etc/nginx/sites-available/default ]]; then
    rm -- /etc/nginx/sites-enabled/default
fi
if [[ -e /etc/nginx/sites-enabled/cyberwatch && ! -L /etc/nginx/sites-enabled/cyberwatch ]]; then
    echo 'Refusing to replace an unmanaged Nginx enabled-site file.' >&2; exit 1
fi
if [[ -L /etc/nginx/sites-enabled/cyberwatch && $(readlink -f /etc/nginx/sites-enabled/cyberwatch) != /etc/nginx/sites-available/cyberwatch ]]; then
    echo 'Refusing to replace an unmanaged Nginx enabled-site link.' >&2; exit 1
fi
render_nginx() {
    python3 - "$fqdn" "$1" <<'PY'
from pathlib import Path
import sys
name = sys.argv[2]
if name not in {'nginx-http.conf.template', 'nginx-https.conf.template'}:
    raise RuntimeError('Unexpected proxy template')
config = (Path('/opt/cyberwatch/azure') / name).read_text().replace('@@FQDN@@', sys.argv[1])
path = Path('/etc/nginx/sites-available/cyberwatch')
path.write_text(config)
path.chmod(0o644)
PY
}
if [[ -s "/etc/letsencrypt/live/$fqdn/fullchain.pem" && -s "/etc/letsencrypt/live/$fqdn/privkey.pem" ]]; then
    render_nginx nginx-https.conf.template
else
    render_nginx nginx-http.conf.template
fi
ln -sfn /etc/nginx/sites-available/cyberwatch /etc/nginx/sites-enabled/cyberwatch
nginx -t
systemctl daemon-reload
systemctl enable nginx.service cyberwatch.service cyberwatch-backup.timer cyberwatch-health.timer certbot.timer >/dev/null
systemctl restart nginx.service
# Only public ACME challenge files bypass authentication; every other HTTP path
# redirects to HTTPS even before the first certificate has been provisioned.
certbot certonly --webroot -w /var/lib/letsencrypt --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring --cert-name "$fqdn" -d "$fqdn" >/dev/null
render_nginx nginx-https.conf.template
nginx -t
systemctl reload nginx.service
systemctl restart cyberwatch.service
ready=false
for attempt in $(seq 1 60); do
    if curl --silent --fail --max-time 2 http://127.0.0.1:8080/ready >/dev/null; then ready=true; break; fi
    sleep 2
done
[[ "$ready" == true ]] || { echo 'Application did not become ready; inspect managed service logs.' >&2; exit 1; }
systemctl start cyberwatch-backup.timer cyberwatch-health.timer certbot.timer
systemctl start cyberwatch-backup.service
printf 'Live application installed at https://%s; private credentials preserved on the host.\n' "$fqdn"
