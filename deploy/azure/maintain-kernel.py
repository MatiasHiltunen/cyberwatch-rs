#!/usr/bin/env python3
"""Stage the supported Noble Azure LTS kernel without removing a boot fallback.

As root: python3 maintain-kernel.py prepare
Reboot separately, verify the application/data, then run the `finalize` command.
Finalize only reports a removal plan; an operator must review/simulate any purge.
No version-specific GRUB default is saved: such a pin would bypass future LTS
updates. Until the old higher-versioned kernel is removed, another ordinary boot
will select it. Keep the receipt until the migration and subsequent boot pass.

Canonical procedure: https://ubuntu.com/cloud/public-cloud/docs/
all-clouds-how-to/migrate-kernel-variants/
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import uuid

META = 'linux-azure-lts-24.04'
STATE = Path('/var/lib/cyberwatch-kernel-migration.json')
GRUB = Path('/boot/grub/grub.cfg')
BOOT = Path('/proc/sys/kernel/random/boot_id')
TRACKING = {'linux-azure', 'linux-image-azure', 'linux-headers-azure',
            'linux-cloud-tools-azure', 'linux-tools-azure'}


def command(*args, timeout=30):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                            env={**os.environ, 'LC_ALL': 'C',
                                 'DEBIAN_FRONTEND': 'noninteractive'})
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): '
                           f'{result.stderr[-1500:]}')
    return result.stdout.strip()


def installed():
    output = command('dpkg-query', '-W',
                     '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n')
    return {name.split(':')[0]: version for name, version, status in
            (line.split('\t') for line in output.splitlines())
            if status == 'installed'}


def host_guard():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    release = dict(line.split('=', 1) for line in
                   Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or \
            release.get('VERSION_ID', '').strip('"') != '24.04' or \
            command('dpkg', '--print-architecture') != 'arm64':
        raise RuntimeError('This helper is restricted to Ubuntu 24.04 ARM64')


def boot_id():
    return str(uuid.UUID(BOOT.read_text().strip()))


def grub_guard():
    # A writable environment block is necessary for one-shot selection to clear.
    mounts = json.loads(command('findmnt', '--json', '--target', str(GRUB.parent),
                                '--output', 'SOURCE,FSTYPE'))['filesystems']
    if len(mounts) != 1 or mounts[0]['fstype'] != 'ext4':
        raise RuntimeError('One-shot staging requires this VM\'s plain ext4 boot filesystem')
    source = mounts[0]['source']
    if not re.fullmatch(r'/dev/[A-Za-z0-9/_.-]+', source):
        raise RuntimeError('Ambiguous boot device')
    kinds = set(command('lsblk', '--inverse', '--noheadings', '--output', 'TYPE',
                        source).split())
    if not kinds or not kinds <= {'part', 'disk'}:
        raise RuntimeError('GRUB environment on LVM/RAID/encryption is unsupported here')
    text = GRUB.read_text()
    if not re.search(r'set default="\$\{next_entry\}"', text) or \
            'save_env next_entry' not in text or not re.search(
                r'else\s+set default="0"\s+fi', text):
        raise RuntimeError('Expected GRUB one-shot handling and default 0 are absent')
    return text


def next_entry():
    values = dict(line.split('=', 1) for line in
                  command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
                  if '=' in line)
    return values.get('next_entry', '')


def menu_entry(text, kernel):
    # Read generated IDs, including the submenu, instead of assuming menu indexes.
    entries = []
    for line in text.splitlines():
        if not re.match(r'^\s*(submenu|menuentry) ', line):
            continue
        words = shlex.split(line)
        ids = [words[index + 1] for index, word in enumerate(words[:-1])
               if word in ('$menuentry_id_option', '--id')]
        if len(ids) == 1:
            entries.append((words[0], ids[0]))
    prefix = f'gnulinux-{kernel}-advanced-'
    targets = [value for kind, value in entries
               if kind == 'menuentry' and value.startswith(prefix)]
    if len(targets) != 1:
        raise RuntimeError('Expected exactly one normal LTS kernel GRUB entry')
    target = targets[0]
    submenu = 'gnulinux-advanced-' + target[len(prefix):]
    if entries.count(('submenu', submenu)) != 1 or not re.fullmatch(
            r'[A-Za-z0-9_.:+-]+', target):
        raise RuntimeError('Expected unique parent GRUB submenu is absent')
    return submenu + '>' + target


def save_state(state):
    descriptor = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(state, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(STATE.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare():
    if os.path.lexists(STATE):
        raise RuntimeError('Migration receipt exists; inspect it before another prepare')
    current = command('uname', '-r')
    if not re.fullmatch(r'6\.17\.0-\d+-azure', current):
        raise RuntimeError('Prepare expects the existing 6.17 Azure kernel')
    before = installed()
    if 'linux-image-' + current not in before:
        raise RuntimeError('Current kernel package is not installed; no verified fallback')
    grub_guard()
    if next_entry():
        raise RuntimeError('Another one-shot boot is already pending')
    options = ('install', '--no-install-recommends', '--no-remove', META)
    simulation = command('apt-get', '--simulate', *options, timeout=120)
    if re.search(r'^(Remv|Purg) ', simulation, re.MULTILINE):
        raise RuntimeError('APT simulation would remove packages')
    command('apt-get', '-y', *options, timeout=1200)
    packages = installed()
    if META not in packages or 'linux-image-' + current not in packages:
        raise RuntimeError('Expected LTS meta and original kernel are not both installed')
    candidates = [name.removeprefix('linux-image-') for name in packages
                  if re.fullmatch(r'linux-image-6\.8\.0-\d+-azure', name)]
    if not candidates:
        raise RuntimeError('No installed Azure 6.8 LTS image found')
    target = candidates[0]
    for candidate in candidates[1:]:
        result = subprocess.run(('dpkg', '--compare-versions', candidate, 'gt', target),
                                timeout=10, check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot compare installed kernel versions')
        if result.returncode == 0:
            target = candidate
    for kernel in (current, target):
        for path in (Path('/boot/vmlinuz-' + kernel),
                     Path('/boot/initrd.img-' + kernel)):
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f'Missing boot artifact: {path.name}')
        if not Path('/lib/modules', kernel).is_dir():
            raise RuntimeError('Missing kernel modules')
    command('update-grub', timeout=120)
    entry = menu_entry(grub_guard(), target)
    if next_entry():
        raise RuntimeError('A competing one-shot boot appeared; refusing to overwrite')
    state = {'schema': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
             'bootId': boot_id(), 'previousKernel': current, 'targetKernel': target,
             'metaPackage': META, 'metaVersion': packages[META], 'grubEntry': entry}
    # Persist intent before touching boot selection; interrupted attempts fail closed.
    save_state(state)
    command('grub-reboot', entry)
    if next_entry() != entry:
        raise RuntimeError('One-shot GRUB selection did not persist')
    return {**state, 'status': 'one-shot-staged', 'rebootPerformed': False,
            'packagesRemoved': [], 'receipt': str(STATE)}


def finalize():
    metadata = STATE.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or \
            stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError('Migration receipt must be a root-owned 0600 regular file')
    state = json.loads(STATE.read_text())
    target = state.get('targetKernel', '')
    if state.get('schema') != 1 or state.get('metaPackage') != META or \
            not re.fullmatch(r'6\.8\.0-\d+-azure', target):
        raise RuntimeError('Unexpected migration receipt')
    if boot_id() == state['bootId'] or command('uname', '-r') != target:
        raise RuntimeError('A different boot running the staged LTS kernel is required')
    if next_entry():
        raise RuntimeError('GRUB did not clear its one-shot entry; inspect before proceeding')
    packages = installed()
    if META not in packages or 'linux-image-' + target not in packages:
        raise RuntimeError('Target kernel and LTS tracking meta must remain installed')
    old = {name: version for name, version in packages.items()
           if name.startswith('linux-') and
           (re.search(r'(^|-)6\.17(?:\.|-)', name) or
            (name in TRACKING and version.startswith('6.17.')))}
    return {'status': 'boot-verified-removal-plan-only', 'runningKernel': target,
            'bootId': boot_id(), 'previousBootId': state['bootId'],
            'packagesToReviewForRemoval': dict(sorted(old.items())),
            'simulationCommand': ['apt-get', '--simulate', 'purge', *sorted(old)]
                if old else [], 'packagesRemoved': [], 'persistentGrubPin': False,
            'nextStep': 'Review purge simulation, retain all LTS packages, remove only '
                        'approved obsolete packages, update-grub and verify another boot. '
                        'Until then default 0 can select the retained 6.17 kernel.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'finalize'))
    args = parser.parse_args()
    try:
        host_guard()
        result = prepare() if args.action == 'prepare' else finalize()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
