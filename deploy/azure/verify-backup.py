#!/usr/bin/env python3
"""Verify and restore an exported Azure backup into a new local test database."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--export-report', type=Path, default=ROOT / 'reports/azure/backup-export.json')
parser.add_argument('--output', type=Path, default=ROOT / 'reports/azure/backup-verification.json')
options = parser.parse_args()
spec = importlib.util.spec_from_file_location('backup', ROOT / 'tools/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
report = json.loads(options.export_report.read_text())
name = report['downloaded']
if not re.fullmatch(r'backup-[A-Za-z0-9-]+\.tar\.gz', name):
    raise RuntimeError('Invalid exported backup filename')
archive = options.export_report.parent / name
if archive.is_symlink() or not archive.is_file():
    raise RuntimeError('Expected a regular downloaded backup archive')
with archive.open('rb') as source:
    digest = hashlib.file_digest(source, 'sha256').hexdigest()
if digest != report['sha256'] or digest != report['guestSha256'] or archive.stat().st_size != report['bytes']:
    raise RuntimeError('Downloaded archive hash or size differs from guest evidence')
expected = report['guestEvidence']['backup']['backup']
if not re.fullmatch(r'cyberwatch-live-\d{8}T\d{6}Z\.db', expected):
    raise RuntimeError('Invalid guest snapshot filename')
options.output.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='offvm-restore-', dir=options.output.parent) as temporary:
    output = Path(temporary)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if (len(members) != 2 or {m.name for m in members} != {expected, expected[:-3] + '.json'}
                or any(not m.isfile() or m.size > 512 * 1024 * 1024 for m in members)):
            raise RuntimeError('Unexpected backup archive contents')
        for member in members:
            with tar.extractfile(member) as source, (output / member.name).open('xb') as target:
                shutil.copyfileobj(source, target)
    source = output / expected
    verified = backup.verify(source)
    manifest = json.loads(source.with_suffix('.json').read_text())
    if verified['sha256'] != report['guestEvidence']['backup']['sha256'] or verified['sha256'] != manifest['sha256']:
        raise RuntimeError('Inner snapshot checksum mismatch')
    restored_path = output / 'restored-live-check.db'
    restored = backup.restore(source, restored_path, app_stopped=True)
    with closing(backup.readonly(source)) as original, closing(backup.readonly(restored_path)) as recovered:
        original_ids = original.execute('SELECT id FROM items ORDER BY id').fetchall()
        recovered_ids = recovered.execute('SELECT id FROM items ORDER BY id').fetchall()
    if not original_ids or original_ids != recovered_ids:
        raise RuntimeError('Restored application record IDs differ from snapshot')
    record = {'status': 'passed', 'blob': report['blob'], 'transferSha256': digest,
              'snapshot': {k: v for k, v in verified.items() if k != 'path'},
              'restored': {k: v for k, v in restored.items() if k != 'path'},
              'itemsPreserved': len(original_ids),
              'scope': 'Off-VM backup transfer and snapshot hashes, SQLite integrity, and all item IDs restored into a new local database. The live database was not replaced.'}
options.output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps(record, indent=2))
