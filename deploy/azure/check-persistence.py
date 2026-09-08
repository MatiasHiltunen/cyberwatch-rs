#!/usr/bin/env python3
"""Verify a real VM reboot without changing application rows.

Run as root: python3 check-persistence.py before
Reboot the VM separately, then: python3 check-persistence.py after
A failed check preserves its marker and baseline for investigation. The baseline
is retained as evidence after success; archive/remove it explicitly before a new drill.
"""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import time
import urllib.request
import uuid

ENV = Path('/etc/cyberwatch/app.env')
DATA = Path('/srv/cyberwatch-data')
BASELINE = Path('/var/lib/cyberwatch-persistence-check.json')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
TABLE = '_cyberwatch_deployment_probe'
KIND = 'cyberwatch-reboot-probe-v1'
CREATE_SQL = f'CREATE TABLE "{TABLE}" (nonce TEXT NOT NULL PRIMARY KEY, marker_kind TEXT NOT NULL)'
UNITS = ('cyberwatch.service', 'nginx.service', 'cyberwatch-health.timer',
         'cyberwatch-backup.timer', 'certbot.timer')


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f'{args[0]} check failed with exit status {result.returncode}')
    return result.stdout.strip()


def database():
    paths = [line.split('=', 1)[1] for line in ENV.read_text().splitlines()
             if line.startswith('DATABASE_PATH=')]
    if len(paths) != 1 or not re.fullmatch(r'/app/data/[A-Za-z0-9_.-]+\.db', paths[0]):
        raise RuntimeError('Configured database path is ambiguous or unsafe')
    path = DATA / 'app' / Path(paths[0]).name
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
        raise RuntimeError('Database must be an existing regular file without symlink components')
    return path


def environment():
    boot = str(uuid.UUID(BOOT_ID.read_text().strip()))
    mounts = json.loads(command('findmnt', '--json', '--mountpoint', str(DATA),
                                '--output', 'UUID,FSTYPE'))['filesystems']
    if len(mounts) != 1 or mounts[0].get('fstype') != 'ext4':
        raise RuntimeError('Dedicated data filesystem is not mounted as ext4')
    disk_uuid = str(uuid.UUID(mounts[0]['uuid']))
    return boot, disk_uuid


def connect(path):
    connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    connection.execute('PRAGMA trusted_schema=OFF')
    deadline = time.monotonic() + 45
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    return connection


def save_baseline(state):
    # Exclusive creation refuses overwrites and symlinks, including a concurrent drill.
    descriptor = os.open(BASELINE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as destination:
        json.dump(state, destination, indent=2)
        destination.write('\n')
        destination.flush()
        os.fsync(destination.fileno())
    descriptor = os.open(BASELINE.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def before():
    if os.path.lexists(BASELINE):
        raise RuntimeError('A persistence baseline already exists; inspect it before starting another drill')
    path = database()
    boot, disk_uuid = environment()
    nonce = secrets.token_hex(32)
    with closing(connect(path)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT name FROM sqlite_master WHERE name = ? COLLATE NOCASE', (TABLE,)).fetchone():
            raise RuntimeError('Probe table name already exists; no existing object will be reused or replaced')
        items = connection.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        if items <= 0:
            raise RuntimeError('Expected an already populated live database')
        state = {'kind': KIND, 'nonce': nonce, 'boot_id': boot, 'filesystem_uuid': disk_uuid,
                 'database': str(path), 'items_before': items,
                 'created_at': datetime.now(timezone.utc).isoformat()}
        connection.execute(CREATE_SQL)
        connection.execute(f'INSERT INTO "{TABLE}" VALUES (?, ?)', (nonce, KIND))
        # Durable evidence is published before the marker transaction commits.
        # An interrupted preparation is deliberately fail-closed on the next run.
        save_baseline(state)
        connection.commit()
    return {'status': 'armed', 'boot_id': boot, 'filesystem_uuid': disk_uuid,
            'items_before': items, 'probe_sha256': hashlib.sha256(nonce.encode()).hexdigest(),
            'baseline': str(BASELINE)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Readiness checks never follow redirects')


def runtime_checks():
    states = {}
    for unit in UNITS:
        states[unit] = {'active': command('systemctl', 'is-active', unit),
                        'enabled': command('systemctl', 'is-enabled', unit)}
        if states[unit] != {'active': 'active', 'enabled': 'enabled'}:
            raise RuntimeError(f'Required service/timer is not active and enabled: {unit}')
    command('nginx', '-t')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 60
    while True:
        try:
            with opener.open('http://127.0.0.1:8080/ready', timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError('Application readiness is not successful')
            with opener.open('http://127.0.0.1:8080/health', timeout=3) as response:
                health = json.loads(response.read(16384))
            if health.get('demo_mode') is not False or health.get('refresh_enabled') is not True:
                raise RuntimeError('Expected live feeds with refresh enabled')
            if command('docker', 'inspect', '--format', '{{.State.Health.Status}}', 'cyberwatch') != 'healthy':
                raise RuntimeError('Container has not reached healthy status')
            return {'units': states, 'nginx_configuration': 'passed', 'readiness': 'passed',
                    'container_health': 'healthy', 'demo_mode': False, 'refresh_enabled': True}
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def after():
    if BASELINE.is_symlink() or not BASELINE.is_file() or BASELINE.stat().st_size > 16384:
        raise RuntimeError('No valid persistence baseline exists')
    if BASELINE.stat().st_uid != 0 or BASELINE.stat().st_mode & 0o077:
        raise RuntimeError('Persistence baseline must be root-owned with mode 0600')
    state = json.loads(BASELINE.read_text())
    if state.get('kind') != KIND or not re.fullmatch(r'[a-f0-9]{64}', state.get('nonce', '')):
        raise RuntimeError('Persistence baseline format is invalid')
    path = database()
    boot, disk_uuid = environment()
    if boot == state['boot_id']:
        raise RuntimeError('Boot ID did not change; no VM reboot has been demonstrated')
    if disk_uuid != state['filesystem_uuid'] or str(path) != state['database']:
        raise RuntimeError('Data filesystem or configured database changed across the reboot')
    checks = runtime_checks()
    with closing(connect(path)) as connection:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('Database integrity check failed')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('Database foreign-key check failed')
        connection.execute('BEGIN IMMEDIATE')
        schema = connection.execute('SELECT type, sql FROM sqlite_master WHERE name = ?', (TABLE,)).fetchone()
        if schema != ('table', CREATE_SQL):
            raise RuntimeError('Probe table definition is missing or changed; no cleanup performed')
        if connection.execute(f'SELECT nonce, marker_kind FROM "{TABLE}"').fetchall() != [(state['nonce'], KIND)]:
            raise RuntimeError('Exact persistence nonce did not survive; no cleanup performed')
        items = connection.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        if items <= 0:
            raise RuntimeError('Live database has no application items after reboot')
        # All verification passed. Remove only our exact table with the matching nonce.
        connection.execute(f'DROP TABLE "{TABLE}"')
        connection.commit()
    return {'status': 'passed', 'boot_id_before': state['boot_id'], 'boot_id_after': boot,
            'filesystem_uuid': disk_uuid, 'items_before': state['items_before'], 'items_after': items,
            'probe_sha256': hashlib.sha256(state['nonce'].encode()).hexdigest(),
            'nonce_survived': True, 'integrity': 'ok', 'probe_table_removed': True,
            'baseline_retained': str(BASELINE), **checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'after'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run this bounded persistence check as root')
    os.umask(0o077)
    result = before() if args.phase == 'before' else after()
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
