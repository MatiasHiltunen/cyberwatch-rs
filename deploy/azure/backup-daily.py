#!/usr/bin/env python3
"""Daily online SQLite backup; prune only this install's verified backup filenames."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re

DESTINATION = Path('/var/backups/cyberwatch')
PATTERN = re.compile(r'cyberwatch-live-\d{8}T\d{6}Z\.db')


def main():
    if DESTINATION.is_symlink() or not DESTINATION.is_dir():
        raise RuntimeError('Backup directory must be a real operator-owned directory')
    configured = [line.split('=', 1)[1] for line in Path('/etc/cyberwatch/app.env').read_text().splitlines()
                  if line.startswith('DATABASE_PATH=')]
    if len(configured) != 1 or not re.fullmatch(r'/app/data/[A-Za-z0-9_.-]+\.db', configured[0]):
        raise RuntimeError('Configured database path requires operator review')
    source = Path('/srv/cyberwatch-data/app') / Path(configured[0]).name
    with (DESTINATION / '.backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        spec = importlib.util.spec_from_file_location('backup', '/opt/cyberwatch/tools/backup.py')
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        target = DESTINATION / f'cyberwatch-live-{stamp}.db'
        result = backup.snapshot(source, target)
        target.chmod(0o600)
        report = target.with_suffix('.json')
        report.write_text(json.dumps(result, indent=2) + '\n')
        report.chmod(0o600)
        snapshots = sorted(path for path in DESTINATION.iterdir()
                           if PATTERN.fullmatch(path.name) and path.is_file() and not path.is_symlink())
        for old in snapshots[:-7]:
            old.unlink()
            old_report = old.with_suffix('.json')
            if old_report.is_file() and not old_report.is_symlink():
                old_report.unlink()
        print(json.dumps({'status': 'passed', 'backup': target.name, 'bytes': result['bytes'],
                          'sha256': result['sha256'], 'retained': min(7, len(snapshots))}))


if __name__ == '__main__':
    os.umask(0o077)
    main()
