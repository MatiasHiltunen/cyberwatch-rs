#!/usr/bin/env python3
"""Mount only the dedicated Azure LUN0; never discover a disk by /dev/sdX order."""
import json
import os
from pathlib import Path
import subprocess
import time

TARGET = Path('/srv/cyberwatch-data')
LABEL = 'CYBERWATCH_DATA'
LINKS = (Path('/dev/disk/azure/scsi1/lun0'), Path('/dev/disk/azure/data/by-lun/0'))


def command(*args, allowed=(0,)):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode not in allowed:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr.strip()}')
    return result.stdout.strip()


def identify():
    found = {path.resolve() for path in LINKS if path.exists()}
    if len(found) != 1:
        raise RuntimeError('Expected exactly one unambiguous Azure LUN0 disk link')
    disk = found.pop()
    root = command('findmnt', '-n', '-o', 'SOURCE', '/').split('[', 1)[0]
    if not root.startswith('/dev/'):
        raise RuntimeError('Cannot establish the OS disk identity safely')
    ancestors = command('lsblk', '-s', '-l', '-n', '-p', '-o', 'NAME', root).splitlines()
    if disk in {Path(name.strip()).resolve() for name in ancestors}:
        raise RuntimeError('Refusing to use an OS disk or ancestor')
    node = json.loads(command('lsblk', '--json', '--bytes', '--paths', '--output',
                             'NAME,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS', str(disk)))['blockdevices']
    if len(node) != 1 or node[0]['type'] != 'disk' or node[0].get('children'):
        raise RuntimeError('LUN0 must be a whole disk without partitions/child devices')
    if int(node[0]['size']) != 4 * 1024 ** 3:
        raise RuntimeError('This installation expects the explicitly provisioned 4 GiB LUN0')
    mounts = [entry for entry in node[0].get('mountpoints', []) if entry]
    if any(entry != str(TARGET) for entry in mounts):
        raise RuntimeError('LUN0 is mounted somewhere else; refusing to change it')
    # Probe directly so an immediately formatted disk does not depend on udev's cache.
    tags = dict(line.split('=', 1) for line in command('blkid', '-p', '-o', 'export',
                                                      str(disk), allowed=(0, 2)).splitlines() if '=' in line)
    node[0]['fstype'] = tags.get('TYPE')
    node[0]['label'] = tags.get('LABEL')
    return disk, node[0]


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run disk preparation as root')
    deadline = time.monotonic() + 90
    while not any(path.exists() for path in LINKS) and time.monotonic() < deadline:
        time.sleep(1)
    disk, node = identify()
    if not node.get('fstype'):
        if any(node.get('mountpoints', [])):
            raise RuntimeError('Unformatted disk unexpectedly has a mount')
        if command('wipefs', '--no-act', '--noheadings', '--output', 'TYPE', str(disk)):
            raise RuntimeError('LUN0 contains an existing signature; refusing to format')
        print('Checking the entire newly provisioned 4 GiB LUN0 for zero-filled contents.', flush=True)
        scanned = 0
        scan_started = time.monotonic()
        zero = bytes(4 * 1024 ** 2)
        with disk.open('rb', buffering=0) as source:
            while chunk := source.read(len(zero)):
                if time.monotonic() - scan_started > 300:
                    raise RuntimeError('Blank disk scan exceeded five minutes; no formatting performed')
                if chunk != zero[:len(chunk)]:
                    raise RuntimeError('LUN0 contains nonzero data; refusing to format')
                scanned += len(chunk)
                if scanned % (1024 ** 3) == 0:
                    print(f'Blank disk check: {scanned // 1024 ** 3}/4 GiB.', flush=True)
        if scanned != 4 * 1024 ** 3 or identify()[1].get('fstype'):
            raise RuntimeError('Disk changed during the blank check')
        command('mkfs.ext4', '-q', '-L', LABEL, str(disk))
        disk, node = identify()
    if node.get('fstype') != 'ext4' or node.get('label') != LABEL:
        raise RuntimeError('Existing LUN0 is not the managed Cyberwatch ext4 filesystem')
    uuid = command('blkid', '-p', '-s', 'UUID', '-o', 'value', str(disk))
    if not uuid or any(char not in '0123456789abcdef-' for char in uuid):
        raise RuntimeError('Filesystem UUID is not valid')
    if TARGET.is_symlink():
        raise RuntimeError('Data mount path may not be a symlink')
    TARGET.mkdir(mode=0o755, parents=True, exist_ok=True)
    current = command('findmnt', '-n', '--mountpoint', str(TARGET), '-o', 'SOURCE', allowed=(0, 1))
    if current and Path(current).resolve() != disk:
        raise RuntimeError('Data mount path already belongs to another filesystem')
    fstab = Path('/etc/fstab')
    lines = fstab.read_text().splitlines()
    entries = [line.split() for line in lines if line.strip() and not line.lstrip().startswith('#')]
    existing = [entry for entry in entries if len(entry) > 1 and entry[1] == str(TARGET)]
    if existing and (len(existing) != 1 or existing[0][0] != 'UUID=' + uuid):
        raise RuntimeError('Conflicting data mount in fstab; refusing to edit it')
    if not existing:
        with fstab.open('a') as destination:
            destination.write(f'\nUUID={uuid} {TARGET} ext4 defaults,nodev,nosuid,noexec,nofail,x-systemd.device-timeout=90 0 2 # cyberwatch-managed-data\n')
    if not current:
        command('mount', str(TARGET))
    if command('findmnt', '-n', '--mountpoint', str(TARGET), '-o', 'UUID') != uuid:
        raise RuntimeError('Mounted filesystem UUID does not match the verified disk')
    for name in ('app',):
        path = TARGET / name
        if path.is_symlink():
            raise RuntimeError('Managed data directory cannot be a symlink')
        path.mkdir(exist_ok=True)
        os.chown(path, 10001, 0)
        path.chmod(0o2770)
    print('Verified dedicated data filesystem mounted persistently; existing database preserved.')


if __name__ == '__main__':
    main()
