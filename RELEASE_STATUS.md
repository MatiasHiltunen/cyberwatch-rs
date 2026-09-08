# Current example verification status

Prepared 2026-09-08 from the supplied Cyberwatch source. Original file hashes are retained in [docs/evidence/source-baseline.json](docs/evidence/source-baseline.json). Historical archive assembly checks are not carried forward as validation of this changed version. This example now includes an authorized live Azure teaching deployment; it is not a published release or a completed course submission.

The workspace was subsequently upgraded to Rust 1.98.1; the [upgrade run record](docs/evidence/rust-1.98.1-upgrade.md) records its native checks and container limitation. Existing image scans, size measurements and Azure deployment evidence below describe the earlier Rust 1.88.0 artifacts; they are not validation of a rebuilt 1.98.1 image.

| Verification | Actual status |
|---|---|
| Native Rust/API tests | 35 tests passed on Windows ARM64 using Rust 1.98.1 (debug profile with debug symbols disabled): 25 library, 3 probe unit, 2 real healthcheck CLI and 5 HTTP integration tests; earlier optimized 1.88.0 evidence is retained |
| Python regression tests | 23 passed: recovery, deployment rollback/provenance boundary, policy, smoke-target isolation and runtime archive safety/determinism |
| Kustomize local/Rahti/maintenance rendering | Rendered successfully; server validation and real cluster behavior not established |
| Source/schema/policy/JavaScript, Rustfmt, Clippy, locked build | Passed with Rust 1.98.1; Clippy reported six collapsible_if style suggestions and no correctness errors |
| Native-process offline HTTP smoke | 14 requests passed, including pagination, filtering, invalid queries, unknown API, disabled refresh, headers and metrics |
| Compose configurations | Default, live, monitoring and optional maintenance configurations validated |
| Dev Container | Linux ARM64 image/container and Rust 1.98.1 tools verified; private token setup, dependency fetch and 23 Python/source/policy/JavaScript checks passed. App started and all 14 HTTP checks passed from Windows through localhost-only Docker publishing; see docs/evidence/devcontainer-local-access.md. Zed GUI attachment and full Linux Rust test suite were not run |
| Local Trivy 0.74.0 repository scan | HIGH/CRITICAL vulnerability, secret and supported configuration scans passed; the separate Azure source report and scope limits are in docs/evidence/azure-security-status.md |
| Production image security scan | Current Linux ARM64 production image passed HIGH/CRITICAL vulnerability and secret scan; exact report in docs/evidence/production-security-scan.json |
| Maintenance image security scan | Pinned Alpine/Python image with reviewed libuuid security update passed HIGH/CRITICAL vulnerability and secret scan; exact report in docs/evidence/maintenance-security-scan.json. Nine recovery regression tests also passed inside this image |
| SBOMs | Current source, production and maintenance inventories are retained as separate CycloneDX documents in docs/evidence/ |
| Docker build/container smoke | Linux ARM64 production built and passed 14 HTTP checks, gzip negotiation, scheduled exec-form healthcheck and missing-listener failure under read-only/non-root restrictions |
| Runtime archive | Exported five-file Linux ARM64 archive passed size/content/ELF gates; extracted binary/web passed 14 HTTP checks and healthcheck from a read-only volume |
| Production size | Rootfs TAR reduced 156.37 to 40.89 MiB; compressed application archive 3.35 MiB. Exact measurements and limits: docs/production-size.md |
| Hosted CI security scans and DAST | Workflows configured, including both image gates and restored-database startup; no hosted run asserted |
| Registry publication, provenance/signature verification | Workflow/design supplied; not executed |
| Azure live deployment | Deployed in the selected student subscription using Bicep and az: HTTPS, protected reader/admin access, live ingestion, persistent managed disk, private artifact transfer and bounded runtime verified; see docs/azure-deployment.md |
| Azure recovery and persistence | Real VM reboot preserved a unique database marker and filesystem UUID; HTTPS and service/timer checks passed. An off-VM backup restored all 2,226 backed-up item IDs into a new local test database |
| Azure host security | Installed-package gate has unresolved kernel advisories; retained without blanket suppressions. The default end-of-life kernel stream was migrated to the Azure LTS stream; inspect the current scoped reports in docs/evidence/azure-security-status.md |
| Cluster RBAC/egress enforcement and secret rotation | Manifests/procedures supplied; actual cluster enforcement, scoped denial exercises and credential rotation remain separate operator work |
| Local recovery | Real container database backup, checksum/integrity verification, guarded restore, restored startup and unique-marker preservation passed; arbitrary non-root maintenance/restored UID tested |
| Operator recovery and security tabletop | Local technical recovery tested; actual course/platform recovery timing and human tabletop remain pending |
| Reviewed PR, student roles/passport, personal reflection and peer/leadership assessment | Human work pending; templates are not completed evidence |

Run the checked-in entry point on the selected version:

```sh
python -m pip install -r tools/requirements-dev.txt
python tools/check.py
```

`--static` runs the Python/source/policy/browser subset. Docker/hosted checks are defined in [.github/workflows/ci.yml](.github/workflows/ci.yml). Record actual versions, commit, command, outcome and limitations in a [run record](docs/evidence/templates/run-record.md), then select a passing immutable baseline for separate course adoption.

Docker became available during production optimization. Container bridge networking
timed out for build dependencies; the local verification build used `--network host`.
This is an environment workaround, not a production runtime requirement. The
[Azure runbook](docs/azure-deployment.md) records the deployed live endpoint and
its actual authentication, persistence and recovery checks. Effective cluster
RBAC/NetworkPolicy, delivered alerts, Linux AMD64 execution and an end-to-end
hosted pipeline remain unverified. Local tests use synthetic demo data; Azure
uses public live feeds and keeps upstream failures visible. Vulnerability reports
describe their recorded scope and scan time.
