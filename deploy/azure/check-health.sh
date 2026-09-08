#!/usr/bin/env bash
set -euo pipefail
# A one-minute timer acts only after Docker's three failed readiness checks.
health=$(/usr/bin/docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' cyberwatch)
if [[ "$health" == unhealthy ]]; then
    /usr/bin/logger -t cyberwatch-health 'Application readiness is unhealthy; restarting its managed service.'
    /usr/bin/systemctl restart cyberwatch.service
elif [[ "$health" != healthy && "$health" != starting ]]; then
    exit 1
fi
