#!/usr/bin/env python3
"""Restore a verified snapshot to a new file and switch the supervised application."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ENV = Path('/etc/cyberwatch/app.env')
DATA = Path('/srv/cyberwatch-data/app')


def ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with opener.open('http://127.0.0.1:8080/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError('Restored application did not become ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run recovery as root')
    # Verification and destination checks happen before any service interruption.
    subprocess.run(['/usr/bin/python3', '/opt/cyberwatch/tools/backup.py', 'verify', str(args.snapshot)], check=True)
    subprocess.run(['/usr/bin/mountpoint', '-q', '/srv/cyberwatch-data'], check=True)
    name = datetime.now(timezone.utc).strftime('restored-%Y%m%dT%H%M%SZ.db')
    destination = DATA / name
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('Recovery filename already exists; never overwrite it')
    original = ENV.read_text()
    lines = original.splitlines()
    if sum(line.startswith('DATABASE_PATH=') for line in lines) != 1:
        raise RuntimeError('Database configuration is ambiguous')
    # Prevent a health-triggered restart and concurrent backup while changing the DB.
    subprocess.run(['systemctl', 'stop', 'cyberwatch-health.timer', 'cyberwatch-backup.timer'], check=True)
    subprocess.run(['systemctl', 'stop', 'cyberwatch-health.service', 'cyberwatch-backup.service'], check=True)
    try:
        subprocess.run(['systemctl', 'stop', 'cyberwatch.service'], check=True)
        subprocess.run(['/usr/bin/python3', '/opt/cyberwatch/tools/backup.py', 'restore',
                        str(args.snapshot), str(destination), '--app-stopped'], check=True)
        os.chown(destination, 10001, 0)
        destination.chmod(0o660)
        changed = '\n'.join('DATABASE_PATH=/app/data/' + name if line.startswith('DATABASE_PATH=') else line for line in lines) + '\n'
        ENV.write_text(changed)
        ENV.chmod(0o600)
        subprocess.run(['systemctl', 'start', 'cyberwatch.service'], check=True)
        ready()
        print(json.dumps({'status': 'ready', 'database': name,
                          'next_step': 'Verify expected live records before accepting recovery; previous database is retained.'}))
    except Exception:
        # Restore the previous configuration if the new database cannot start.
        subprocess.run(['systemctl', 'stop', 'cyberwatch.service'], check=False)
        ENV.write_text(original)
        ENV.chmod(0o600)
        subprocess.run(['systemctl', 'start', 'cyberwatch.service'], check=False)
        raise
    finally:
        subprocess.run(['systemctl', 'start', 'cyberwatch-health.timer', 'cyberwatch-backup.timer'], check=True)


if __name__ == '__main__':
    os.umask(0o077)
    main()
