# Operations, service objectives, and exercises

The reference application uses one replica and one persistent database volume. This keeps the operational model reproducible but introduces a service interruption during a recreate rollout or maintenance restore. Use [deploy/README.md](../deploy/README.md) for exact platform and backup commands. Exercises below are **procedures, not completed incidents**.

## Readiness, logs, metrics, and proposed objectives

`/health` describes process health and explicit demo/refresh state. `/ready` checks the database. `/metrics` exports bounded route/status HTTP counters and duration histograms plus refresh mode. `/api/v1/sources` and refresh status expose ingestion diagnostics. Demo mode deliberately disables external refresh and uses synthetic data; do not score it against live-feed freshness.

| Signal | Proposed target / trigger | First justified action |
|---|---|---|
| Readiness | Lab objective: at least 99% successful scheduled probes during declared service hours in a 7-day observation window; trigger on two consecutive failed 30-second probes | Check process/pod events, volume mount and database errors before restarting |
| HTTP latency | Lab objective: p95 read-request duration <500 ms over 5 minutes under recorded demonstration load | Compare request rate, admission failures and data size; inspect slow queries before raising concurrency |
| Server errors | Trigger if 5xx fraction >5% for 5 minutes with at least 20 requests; no traffic means “insufficient data,” not 100% success | Check failing route, logs and recent digest rollout; assess rollback compatibility |
| Live ingestion freshness | Trigger when last successful refresh is older than twice configured interval plus maximum source execution time; review per-source failures separately | Check upstream availability/backoff and credentials; do not repeatedly force refresh against a rate-limited source |
| Recoverability | Proposed RPO <=24 hours, RTO <=15 minutes for the bounded lab dataset | Verify newest backup identity/integrity and use guarded restore into a new path |
| Volume and retention | Trigger at 80% of allocated volume or failed write/backup; choose retention with service owner | Stop growth, retain a verified backup, adjust explicit retention/volume within quota |

These numbers are project targets to test, not claims of achieved availability, latency, or recovery. Readiness is not liveness, source freshness is not readiness, and a partial source failure should not automatically restart a healthy API. Memory/CPU/PVC metrics come from the actual platform if available; do not invent application metric names for them.

Prometheus HTTP examples (inspect the exact labels and exported names in your running build):

```promql
sum(rate(cyberwatch_http_requests_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(cyberwatch_http_request_duration_seconds_bucket[5m])))
```

Keep metrics on a restricted operational surface. The example includes [Prometheus/alert configuration](../monitoring/README.md); platform integration and a delivered notification remain operator work. Persist a redacted sample and trigger condition even if no alert service is available; the course permits a documented trigger.

## Incident triage

1. Record UTC detection time, observable symptom, selected commit/image digest, affected environment and recent change. Never include tokens or private records in a public incident note.
2. Classify: API unavailable, database/volume problem, ingestion-only degradation, suspected credential misuse, or release-integrity problem. Identify the incident lead and operational owner.
3. Preserve useful logs, source status and deployment events. Stop risky mutations or live ingestion if confidentiality/integrity is threatened. Do not destroy the only data copy to get readiness green.
4. Choose the smallest justified response: source backoff/disable, scoped secret rotation, compatible image rollback, or guarded data restore. Use the actual deployment guide and verify target namespace/path.
5. Verify readiness, a known query, expected data/mode, old-token denial when rotating, and recovery integrity. Measure restoration time separately from detection time.
6. Update the risk/finding record and backlog. Identify one causal improvement, its owner, acceptance test and date; a transcript of commands alone is not a retrospective.

## Backup and recovery exercise

Use a disposable demo database and a backup destination with enough free space. `tools/backup.py` uses the SQLite online backup API, validates integrity and records a hash; use its help and the deployment guide for the supported subcommands. A raw copy of an open database can omit WAL state and is not this procedure.

Capture the starting image digest, data identity and baseline counts. Produce and verify a backup. For restore, stop the application (zero cluster replicas where applicable), retain the original data and backup, restore to a **new** database filename using the required `--app-stopped` guard, point configuration at that file and restart. Never treat the flag alone as proof that the app is stopped. Confirm readiness, known records, mode marker and integrity, and measure elapsed time against the proposed RTO/RPO.

Adverse cases: altered checksum, corrupted backup, existing destination and missing stop guard must fail safely. Use the automated tests for these cases before touching real data. Disk loss is simulated by a new disposable destination, not deletion of the only source volume. An image rollback is safe only if that version understands the database schema; otherwise restore a compatible backup and measure the accepted data loss.

Current local tooling test status lives in [release status](../RELEASE_STATUS.md). Even passing backup unit tests do not prove cluster volume mounting, storage durability, external backup isolation, or a measured operator recovery.

## Security tabletop

Scenario: a release was deployed 20 minutes ago; refresh behavior changes unexpectedly; the newest image has a tag the team recognizes but no verified expected provenance. At the same time an upstream feed begins returning hostile links. This is a fictional exercise to conduct in the authorized lab; no actual compromise is alleged.

| Inject / facilitator timing | Decision requested | Evidence or observation to record |
|---|---|---|
| Minute 0: anomalous refresh volume and unknown image digest | Who leads, what is contained first, and what observations are preserved? | Detection time, HTTP/source indicators, deployed digest and authorized scope |
| Minute 5: a build credential may be exposed | Revoke which identity; pause which workflow; who informs the owner? | Required versus excessive rights, rotation order, public/private communication boundary |
| Minute 10: previous image available; database may have changed | Is image rollback compatible or must data be restored? | Schema compatibility check, chosen verified backup, expected data loss |
| Minute 15: source data contains untrusted content | Does rendering execute content; can the source contact private services; what is disabled? | Existing controls, adverse tests, remaining egress assumptions |
| Minute 20: service is reachable again | What establishes integrity, not only availability; can release resume? | Verified digest/provenance, known-record query, old-token denial, owner decision |
| Minute 30: retrospective | Which risk assumption changed and which improvement is prioritized? | Updated R03/R05/R07/R08, assigned owner/date, acceptance test |

Assign real incident lead, operator, security reviewer, service owner and recorder. Where one person fills several roles, document that limitation. Capture actual participants, decisions, disagreements, elapsed times and lessons in [run-record.md](evidence/templates/run-record.md). Do not fill these fields from the scenario as though participants actually performed them.

## Teardown and retention

Before expiry, verify a restorable backup and retain the redacted assessment evidence required by the course. Inventory the exact course namespace/Compose project, PVC/volumes, secrets, images and any allocated public endpoint. Follow the bounded teardown commands in the deployment guide. Database volume deletion is an explicit final operator decision after retention needs are met; stopping a workload alone does not remove stored data or all costs. Keep YAMK282 and YAMK283 resources separately identified throughout.
