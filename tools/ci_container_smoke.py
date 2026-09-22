"""Exercise the release container with an ephemeral file secret, never a CLI token."""
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    image = sys.argv[1]
    name = 'cyberwatch-release-check'
    with tempfile.TemporaryDirectory() as directory:
        token = Path(directory) / 'token'
        token.write_text(secrets.token_urlsafe(48), encoding='ascii')
        token.chmod(0o644)  # Its private parent protects the host; runtime UID differs.
        try:
            subprocess.run(['docker', 'run', '-d', '--name', name, '--read-only',
                            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                            '--memory', '512m', '--pids-limit', '128',
                            '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
                            '--tmpfs', '/app/data:rw,uid=10001,gid=0,mode=0770,size=128m',
                            '--mount', f'type=bind,src={token},dst=/run/secrets/admin-token,readonly',
                            '-p', '127.0.0.1:8080:8080', '-e', 'DEMO_MODE=true',
                            '-e', 'REFRESH_ENABLED=false', '-e', 'ADMIN_TOKEN_FILE=/run/secrets/admin-token',
                            image], check=True, stdout=subprocess.DEVNULL)
            for attempt in range(90):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('Release container did not become ready')
            subprocess.run([sys.executable, 'tools/smoke.py', '--url', 'http://127.0.0.1:8080',
                            '--output', 'reports/release-smoke.json'], check=True)
            subprocess.run(['docker', 'exec', name, '/usr/local/bin/cyberwatch-rs', '--healthcheck'], check=True)
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
