#!/usr/bin/env python3
"""Application-only update on an already bootstrapped Cyberwatch VM.

Run as root through Azure Run Command. Input (including an expiring blob SAS)
arrives on stdin and is never logged. No package upgrades, disk formatting,
identity changes, secret rotation or proxy reconfiguration happen here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

CONFIG = Path('/etc/cyberwatch')


def call(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('VM command failed: ' + args[0])
    return result.stdout.strip()


def validate_payload(payload):
    if (not re.fullmatch(r'[a-f0-9]{40}', payload.get('commit', ''))
            or payload.get('image') != 'cyberwatch-release:' + payload['commit']
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', payload.get('imageConfigId', ''))
            or not re.fullmatch(r'[a-f0-9]{64}', payload.get('archiveSha256', ''))
            or not isinstance(payload.get('bytes'), int) or not 0 < payload['bytes'] < 1024**3
            or payload.get('platform') != 'linux/arm64'):
        raise ValueError('Invalid release metadata')
    url = urllib.parse.urlsplit(payload.get('url', ''))
    if (url.scheme != 'https' or not re.fullmatch(r'[a-z0-9]{3,24}\.blob\.core\.windows\.net', url.netloc)
            or url.path != f'/artifacts/releases/{payload["commit"]}/{payload["archiveSha256"]}.tar'
            or not url.query):
        raise ValueError('Unexpected artifact URL')


def image_configuration(archive, payload):
    with tarfile.open(archive) as stream:
        member = stream.getmember('manifest.json')
        if not member.isfile() or not 0 < member.size < 1024**2:
            raise ValueError('Invalid image manifest')
        manifest = json.load(stream.extractfile(member))
        if len(manifest) != 1 or manifest[0].get('RepoTags') != [payload['image']]:
            raise ValueError('Archive tag differs from release')
        member = stream.getmember(manifest[0]['Config'])
        if not member.isfile() or not 0 < member.size < 4 * 1024**2:
            raise ValueError('Invalid image configuration')
        encoded = stream.extractfile(member).read()
        if 'sha256:' + hashlib.sha256(encoded).hexdigest() != payload['imageConfigId']:
            raise ValueError('Image configuration checksum mismatch')
        config = json.loads(encoded)
        if config.get('architecture') != 'arm64' or config.get('os') != 'linux':
            raise ValueError('Unexpected image platform')
        return config


def database_path():
    values = [line.split('=', 1)[1] for line in (CONFIG / 'app.env').read_text().splitlines()
              if line.startswith('DATABASE_PATH=')]
    if len(values) != 1 or not re.fullmatch(r'/app/data/[A-Za-z0-9_.-]+\.db', values[0]):
        raise ValueError('Managed database path is invalid')
    path = Path('/srv/cyberwatch-data/app') / Path(values[0]).name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Existing managed database is required')
    return path


def schema_fingerprint(database):
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        schema = connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        version = connection.execute('PRAGMA user_version').fetchone()[0]
    return hashlib.sha256(json.dumps([version, schema], sort_keys=True).encode()).hexdigest()


def atomic_config(content):
    path = CONFIG / 'runtime.env'
    if path.is_symlink():
        raise ValueError('Refusing a symlink at runtime.env')
    with tempfile.NamedTemporaryFile(mode='w', dir=CONFIG, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def wait_ready(expected_image):
    for attempt in range(60):
        result = subprocess.run(['docker', 'exec', 'cyberwatch', '/usr/local/bin/cyberwatch-rs', '--healthcheck'],
                                capture_output=True, timeout=10)
        if result.returncode == 0:
            active = call(['docker', 'inspect', '--format', '{{.Image}}', 'cyberwatch'])
            if active == expected_image:
                return
        time.sleep(2)
    raise RuntimeError('Candidate did not become ready with the expected image')


def activate(candidate, previous, database):
    """Return image-only rollback evidence; never restore data automatically."""
    before = schema_fingerprint(database)
    call(['systemctl', 'start', 'cyberwatch-backup.service'])
    monitoring_safe = False
    try:
        # The health worker can independently restart the application. Stop the
        # timer first, then drain any in-flight worker before changing runtime.
        call(['systemctl', 'stop', 'cyberwatch-health.timer'])
        call(['systemctl', 'stop', 'cyberwatch-health.service'])
        call(['systemctl', 'stop', 'cyberwatch.service'])
        try:
            atomic_config('CYBERWATCH_IMAGE=' + candidate + '\n')
            call(['systemctl', 'start', 'cyberwatch.service'])
            wait_ready(candidate)
        except Exception:
            call(['systemctl', 'stop', 'cyberwatch.service'])
            # An image rollback is unsafe after an incompatible database migration.
            # Leave the service and health monitoring stopped for operator recovery.
            if schema_fingerprint(database) != before:
                raise RuntimeError('Deployment failed and database schema changed; manual recovery required') from None
            atomic_config(previous)
            # A crashing candidate can exhaust the unit's restart burst while the
            # readiness loop waits. Clear that counter so it cannot block rollback.
            call(['systemctl', 'reset-failed', 'cyberwatch.service'])
            call(['systemctl', 'start', 'cyberwatch.service'])
            old_image = previous.strip().split('=', 1)[1]
            wait_ready(old_image)
            monitoring_safe = True
            raise RuntimeError('Deployment failed; previous image restored and healthy') from None
        monitoring_safe = True
    finally:
        if monitoring_safe:
            call(['systemctl', 'start', 'cyberwatch-health.timer'])


def main():
    import fcntl
    if os.geteuid() != 0:
        raise RuntimeError('Run through the authorized VM deployment operation')
    os.umask(0o077)
    payload = json.load(sys.stdin)
    validate_payload(payload)
    with Path('/run/lock/cyberwatch-deploy.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        call(['mountpoint', '-q', '/srv/cyberwatch-data'])
        call(['systemctl', 'is-active', '--quiet', 'cyberwatch.service'])
        previous = (CONFIG / 'runtime.env').read_text()
        if not re.fullmatch(r'CYBERWATCH_IMAGE=sha256:[a-f0-9]{64}\n?', previous):
            raise ValueError('Previous image must have a recorded immutable digest')
        database = database_path()
        label = call(['docker', 'inspect', '--format', '{{index .Config.Labels "io.cyberwatch.managed"}}', 'cyberwatch'])
        if label != 'azure-live':
            raise RuntimeError('Refusing to replace an unmanaged runtime')
        with tempfile.TemporaryDirectory(prefix='cyberwatch-image-') as directory:
            archive = Path(directory) / 'image.tar'
            # Blob location is validated above. Redirects are rejected rather
            # than forwarding a SAS to another destination.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(payload['url'], timeout=60) as response, archive.open('wb') as destination:
                total = 0
                digest = hashlib.sha256()
                while chunk := response.read(1024**2):
                    total += len(chunk)
                    if total > payload['bytes']:
                        raise ValueError('Oversized archive')
                    digest.update(chunk)
                    destination.write(chunk)
            if total != payload['bytes'] or digest.hexdigest() != payload['archiveSha256']:
                raise ValueError('Archive checksum mismatch')
            expected = image_configuration(archive, payload)
            call(['docker', 'load', '--input', str(archive)])
            actual = json.loads(call(['docker', 'image', 'inspect', payload['image']]))[0]
            if (actual['Config'] != expected['config'] or actual['RootFS']['Layers'] != expected['rootfs']['diff_ids']
                    or actual['Architecture'] != 'arm64' or actual['Os'] != 'linux'):
                raise ValueError('Loaded image differs from reviewed configuration/layers')
            activate(actual['Id'], previous, database)
        report = {key: payload[key] for key in ('commit', 'imageConfigId', 'archiveSha256', 'buildId')}
        report.update(status='passed', runtimeImageId=actual['Id'])
        (CONFIG / 'last-deployment.json').write_text(json.dumps(report) + '\n')
        print('CYBERWATCH_DEPLOY_OK ' + payload['commit'] + ' ' + payload['imageConfigId'])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # The exception can include a SAS URL. Store it only in a private VM log.
        import traceback
        Path('/var/log/cyberwatch-deployment.log').write_text(traceback.format_exc())
        Path('/var/log/cyberwatch-deployment.log').chmod(0o600)
        print('CYBERWATCH_DEPLOY_FAILED: inspect the private VM deployment log', file=sys.stderr)
        raise SystemExit(1)
