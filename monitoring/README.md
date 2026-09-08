# Observe and rehearse recovery

This local view uses the same application metrics as a platform Prometheus scraper.
From the project root, after creating the administrative secret:

```sh
docker compose -f docker-compose.yml -f monitoring/compose.yml up --build -d
```

Open http://127.0.0.1:9090, inspect **Status → Targets**, then query
`cyberwatch_http_requests_total`, `rate(cyberwatch_http_requests_total[5m])`, or
`histogram_quantile(0.95, sum by (le) (rate(cyberwatch_http_request_duration_seconds_bucket{route=~"/api/.*"}[5m])))`.
Generate a small amount of traffic by searching the dashboard. Counters reset on restart;
use rates over a window. Labels use route templates and status classes, never CVE IDs,
search text or credentials. Handler latency does not include full response transmission.

For an authorized, disposable local incident exercise, run `docker compose stop cyberwatch`.
Wait for **Alerts → CyberwatchUnavailable** to become firing (roughly 1–2 minutes),
record the observation and timestamp, then run `docker compose start cyberwatch`.
Check `/ready`, browse sample records, and record the recovery timestamp and alert clearing.
This is a reproducible exercise procedure, not evidence that it has already been performed.
The API-error alert will fire if disabled-refresh responses dominate traffic; avoid treating
intentional demo-mode `POST /api/v1/refresh` checks as a production availability measurement.

Prometheus displays alerts locally. External notification delivery requires a separately
configured Alertmanager and receiver; no contact information or notification credentials
are included. Retention is seven days. Do not expose port9090 publicly.

For Rahti, the base network policy permits the namespace's monitoring pods with
`cyberwatch-access=true` to scrape the app. Configure your authorized
scraper/service discovery accordingly and validate the network policy in that cluster.
Platform scrapers in other namespaces require an explicit reviewed ingress rule.
Follow [the operations runbook](../docs/operations.md) for incident ownership, RTO/RPO,
backup recovery, and evidence recording. The API is public-read; put it behind the
institution's ingress/authentication boundary if the deployment needs restricted access.

Configuration reference: [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
and [alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).
