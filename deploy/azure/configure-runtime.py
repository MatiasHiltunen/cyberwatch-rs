#!/usr/bin/env python3
"""Render private configuration and managed units after verified disk/image setup."""
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path('/etc/cyberwatch')
SECRETS = ROOT / 'secrets'
UNIT_DIR = Path('/etc/systemd/system')


def write(path, content, mode=0o600):
    if path.is_symlink():
        raise RuntimeError(f'Refusing a symlink at managed configuration: {path}')
    path.write_text(content)
    path.chmod(mode)


def main():
    fqdn, image_id = sys.argv[1:]
    ROOT.mkdir(mode=0o700, exist_ok=True)
    ROOT.chmod(0o700)
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    SECRETS.chmod(0o700)
    for name in ('admin-token', 'reader-password'):
        path = SECRETS / name
        if path.is_symlink():
            raise RuntimeError('Secret paths may not be symlinks')
        if not path.exists():
            with path.open('x') as destination:
                destination.write(secrets.token_urlsafe(32) + '\n')
        if len(path.read_text().strip()) < 32:
            raise RuntimeError('Existing secret is too short; refusing to replace it silently')
        path.chmod(0o640 if name == 'admin-token' else 0o600)
    # Keep the chosen recovered database on subsequent software deployments.
    database = '/app/data/cyberwatch.db'
    app_env = ROOT / 'app.env'
    if app_env.exists():
        candidates = [line.split('=', 1)[1] for line in app_env.read_text().splitlines()
                      if line.startswith('DATABASE_PATH=')]
        if len(candidates) != 1 or not re.fullmatch(r'/app/data/[A-Za-z0-9_.-]+\.db', candidates[0]):
            raise RuntimeError('Existing database path requires operator review')
        database = candidates[0]
    write(app_env, '\n'.join([
        'BIND_ADDRESS=0.0.0.0:8080', f'DATABASE_PATH={database}', 'WEB_DIR=/app/web',
        'ADMIN_TOKEN_FILE=/run/secrets/admin-token', 'DEMO_MODE=false', 'REFRESH_ENABLED=true',
        'SOURCE_CONCURRENCY=2', 'VALIDATION_CONCURRENCY=2', 'REFRESH_INTERVAL_SECONDS=1800',
        'SOURCE_TIMEOUT_SECONDS=45', 'HTTP_CONNECT_TIMEOUT_SECONDS=10', 'SOURCE_RETRY_ATTEMPTS=1',
        'VALIDATION_BATCH_SIZE=50', 'NVD_RESULTS_PER_PAGE=500', 'GITHUB_ADVISORY_PAGES=1',
        'MAX_SOURCE_RESPONSE_BYTES=8388608', 'NVD_INITIAL_WINDOW_DAYS=2',
        'NEWS_RETENTION_DAYS=30', 'INGESTION_RUN_RETENTION_DAYS=14', 'RUST_LOG=info', ''
    ]))
    write(ROOT / 'runtime.env', f'CYBERWATCH_IMAGE={image_id}\n')
    write(ROOT / 'endpoint', f'https://{fqdn}\n')
    write(UNIT_DIR / 'cyberwatch.service', '''[Unit]
Description=Cyberwatch live feed server
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
RequiresMountsFor=/srv/cyberwatch-data
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
EnvironmentFile=/etc/cyberwatch/runtime.env
ExecStartPre=/usr/bin/mountpoint -q /srv/cyberwatch-data
ExecStartPre=-/usr/bin/docker rm -f cyberwatch
ExecStart=/usr/bin/docker run --name cyberwatch --label io.cyberwatch.managed=azure-live --network bridge --read-only --user 10001:0 --cap-drop ALL --security-opt no-new-privileges:true --memory 512m --cpus 1 --pids-limit 128 --stop-timeout 30 --log-driver local --log-opt max-size=10m --log-opt max-file=3 --publish 127.0.0.1:8080:8080 --mount type=bind,src=/srv/cyberwatch-data/app,dst=/app/data --mount type=bind,src=/etc/cyberwatch/secrets/admin-token,dst=/run/secrets/admin-token,readonly --tmpfs /tmp:rw,noexec,nosuid,size=32m,mode=1777 --env-file /etc/cyberwatch/app.env ${CYBERWATCH_IMAGE}
ExecStop=-/usr/bin/docker stop --time 30 cyberwatch
ExecStopPost=-/usr/bin/docker rm -f cyberwatch
Restart=always
RestartSec=10
TimeoutStopSec=45
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
''', 0o644)
    write(UNIT_DIR / 'cyberwatch-backup.service', '''[Unit]
Description=Consistent Cyberwatch online backup with seven-snapshot retention
RequiresMountsFor=/srv/cyberwatch-data
After=cyberwatch.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/cyberwatch/azure/backup-daily.py
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
# SQLite's read-only database connection still needs to manage WAL shared-memory
# sidecars. Allow this dedicated directory; backup.py opens the DB with mode=ro.
ReadWritePaths=/var/backups/cyberwatch /srv/cyberwatch-data/app
PrivateTmp=true
TimeoutStartSec=180
''', 0o644)
    write(UNIT_DIR / 'cyberwatch-backup.timer', '''[Unit]
Description=Daily Cyberwatch database backup

[Timer]
OnCalendar=*-*-* 03:15:00 UTC
RandomizedDelaySec=15m
Persistent=true
Unit=cyberwatch-backup.service

[Install]
WantedBy=timers.target
''', 0o644)
    write(UNIT_DIR / 'cyberwatch-health.service', '''[Unit]
Description=Recover an unhealthy Cyberwatch application
After=cyberwatch.service

[Service]
Type=oneshot
ExecStart=/bin/bash /opt/cyberwatch/azure/check-health.sh
TimeoutStartSec=90
NoNewPrivileges=true
''', 0o644)
    write(UNIT_DIR / 'cyberwatch-health.timer', '''[Unit]
Description=Check Cyberwatch health once per minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
Unit=cyberwatch-health.service

[Install]
WantedBy=timers.target
''', 0o644)


if __name__ == '__main__':
    os.umask(0o077)
    main()
