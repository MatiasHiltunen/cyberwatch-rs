# Cyberwatch RS — YAMK course example

Cyberwatch RS is a local-first Rust server and browser dashboard that gathers cyber-security news, vulnerability records, exploitation data, and risk enrichment into an embedded Turso/libSQL database.

The service runs as one executable. It schedules ingestion, normalizes and categorizes records, cross-validates CVEs, exposes a JSON API, and serves the bundled web client without a Node.js build step. Explicit offline demo mode supplies deterministic synthetic intelligence for repeatable assessment and security tests.

Start with the [course map](docs/course-map.md), [assessment guide](docs/assessment-guide.md), [deployment and recovery guide](deploy/README.md), [Azure deployment runbook](docs/azure-deployment.md), [production size guide](docs/production-size.md), and [actual verification status](RELEASE_STATUS.md). The example covers both courses' technical and analytical work; personal learning, real peer review, hosted runs, and independent YAMK283 baseline evidence must still be completed by the learner.

## Included in this bundle

- Complete Rust crate under `src/`
- Embedded database schema in `src/schema.sql`
- NVD, CISA KEV, GitHub advisory, CVE Program, and FIRST EPSS integrations
- Configurable RSS, Atom, and RDF ingestion with 35 built-in feeds
- Source adapter registry for adding new structured integrations
- Bounded source concurrency, request limits, retries, deadlines, backoff, and panic isolation
- Transactional writes and cursor pagination
- Cross-source CVE evidence and confidence calculation
- Responsive browser dashboard under `web/`
- Lean production container, separate maintenance image for database-aware backup/restore, and restricted Docker/Compose and Kubernetes/OpenShift deployment
- CI quality/security gates, negative tests, controlled image publication and provenance workflow
- Course requirement mapping, threat/risk/control analysis, worked findings, operational exercises and individual evidence templates

## Requirements

For a native build:

- Rust 1.98.1 (pinned in `rust-toolchain.toml`, including Rustfmt, Clippy and `rust-src`)
- A C/C++ build toolchain suitable for Rust dependencies
- CA certificates and outbound HTTPS access for ingestion

From the project directory, run `rustup show active-toolchain` to install or verify
that version and its components, then `rustc --version`. If VS Code still reports
the old compiler, run **Rust Analyzer: Restart server** or **Developer: Reload Window**.
After upgrading an existing Dev Container, run **Dev Containers: Rebuild Container**.

Docker can be used instead of installing Rust locally.

## Develop in a Dev Container

Open this folder in VS Code and select **Dev Containers: Reopen in Container**.
The workspace installs the pinned Rust toolchain, native build tools, Python and
Node, and defaults to the offline demo. In its terminal, run `python tools/check.py`
to validate the project, or `cargo run --locked` to serve it on forwarded port 8080.
See [.devcontainer/README.md](.devcontainer/README.md) for setup and cache details.
Development tools and compiler caches stay in this separate development environment.

## Start an offline demo locally

In PowerShell, from this project directory:

```powershell
$env:DEMO_MODE = 'true'
$env:DATABASE_PATH = './data/demo.db'
cargo run --locked
```

On Linux/macOS:

```bash
DEMO_MODE=true DATABASE_PATH=./data/demo.db cargo run --locked
```

Open `http://127.0.0.1:8080`.

The demo uses `./data/demo.db`, labels synthetic data, and disables external refresh. `/health` reports `demo_mode` and `refresh_enabled`; `/ready` verifies database access. Reusing a demo database for live ingestion (or seeding demo data into an existing live database) is rejected.

For live ingestion, use a separate database, set `DEMO_MODE=false`, review `.env.example`, and run `cargo run --release --locked`. The default live database is `./data/cyberwatch.db`; refresh begins at startup unless disabled. Live ingestion needs outbound HTTPS and optional upstream credentials. Protect network deployments as described in [SECURITY.md](SECURITY.md).

## Start with Docker

Create a local untracked administrative secret once, then start the deterministic offline demo. The creation command refuses to overwrite an existing token and does not print it:

```bash
python tools/create_admin_secret.py
docker compose config --quiet
docker compose up --build -d
```

The dashboard is available at `http://127.0.0.1:8080`, and a named volume persists its database. Restrict `secrets/` access to your account and retain the token on subsequent runs. Containers bind their internal network, so even demo mode requires the mounted token. The container runs with restricted privileges and a read-only root filesystem.

The default `production` image uses a pinned distroless runtime and contains the executable, three dashboard assets, and license alongside required runtime libraries. It has no shell, Python, compiler, or backup tools. Build the separate Docker `maintenance` target for backup/restore as described in [deploy/README.md](deploy/README.md).

Docker health checks run `cyberwatch-rs --healthcheck`. This checks the running server's `/ready` endpoint with a bounded TCP probe before loading configuration, opening a database, or starting Tokio. It reads the process `BIND_ADDRESS` environment variable, defaults to `127.0.0.1:8080`, and converts wildcard binds to loopback; it does not read `.env`. Missing database schema, connection failure, and non-200 responses fail the probe.

Use the separate live Compose project and volume described in [deploy/README.md](deploy/README.md). All non-loopback configurations require a token of at least 32 bytes at startup. Demo refresh remains disabled even with a valid token.

## Validate the project

```bash
python -m pip install -r tools/requirements-dev.txt
python tools/check.py
```

This runs source/schema validation, backup and policy regression tests, JavaScript syntax, formatting, Clippy correctness, Rust/API tests, build, and a real-process offline HTTP smoke test. `make check` is also available. Current results and checks that need Docker/hosted services are in [RELEASE_STATUS.md](RELEASE_STATUS.md).

To run only checks that do not require the Rust compiler:

```bash
python tools/check.py --static
```

## Build source and runtime distributions

```bash
make bundle
```

`make bundle` creates the source/course ZIP. `tools/package.py` validates the project, builds `../cyberwatch-rs.zip`, tests the ZIP CRC, and refuses to complete unless the archive contains the Rust crate, database schema, ingestion adapters, dashboard, and README. It also writes `../cyberwatch-rs.zip.sha256`.

For a minimal deployable runtime archive:

```bash
docker build --target production -t cyberwatch:local .
python tools/runtime_artifact.py --image cyberwatch:local
```

This writes `dist/cyberwatch-rs-linux-<architecture>.tar.gz`, a SHA-256 checksum, and `dist/runtime-size.json`. Linux `amd64` and `arm64` are supported. The archive contains only the executable, three dashboard assets, and license; the host must provide compatible glibc/libgcc runtime libraries. Source, course documents, tests, development files, and backup tools belong to their separate distributions.

Release builds use size optimization, full LTO, and stripped symbols while retaining panic unwinding for source adapter isolation. CI checks image, filesystem, binary, and compressed archive size against [the size policy](tools/runtime_size_policy.json), validates the executable architecture, and rejects development/maintenance content in production. See [production size and compatibility](docs/production-size.md) for measurements and limits.

## Data sources

Structured sources are registered in `src/ingest/mod.rs`:

| Source | Purpose |
|---|---|
| NIST NVD | Incremental CVE metadata, descriptions, CVSS, status, and CPE data |
| CISA KEV | Authoritative known-exploitation status and remediation deadlines |
| GitHub reviewed advisories | Independent advisory, package, severity, and CVSS evidence |
| CVE Program API | Canonical CVE existence and record status validation |
| FIRST EPSS | Exploitation probability and percentile enrichment |

The default feed catalog includes government CERTs, national cyber-security centers, vendor security teams, research organizations, and established security publications. See `sources.default.json` for the full list.

Feed failures are isolated. One unavailable source does not cancel the rest of a refresh.

## Source customization

Set `SOURCE_CONFIG_PATH` to a JSON file, or put the JSON document directly in `NEWS_FEEDS_JSON`.

```json
{
  "include_defaults": true,
  "feeds": [
    {
      "id": "example-cert",
      "name": "Example CERT",
      "url": "https://security.example.org/feed.xml",
      "region": "Europe",
      "language": "en",
      "trust": 3,
      "role": "official-government-advisory",
      "enabled": true,
      "timeout_seconds": 45,
      "retry_attempts": 1
    }
  ]
}
```

Matching IDs replace built-in feed definitions. Set `enabled` to `false` to omit a custom entry. Structured sources and feeds can also be disabled with a comma-separated list:

```dotenv
DISABLED_SOURCES=nvd,feed-example-cert
```

Feed IDs are prefixed with `feed-` when registered.

## Important configuration

All settings are documented in `.env.example`.

| Variable | Default | Purpose |
|---|---:|---|
| `BIND_ADDRESS` | `127.0.0.1:8080` | HTTP listen address |
| `DATABASE_PATH` | `./data/cyberwatch.db` | Local database file |
| `REFRESH_INTERVAL_SECONDS` | `900` | Scheduled refresh interval |
| `SOURCE_CONCURRENCY` | `8` | Maximum simultaneous source adapters |
| `SOURCE_TIMEOUT_SECONDS` | `120` | General source request timeout |
| `MAX_SOURCE_RESPONSE_BYTES` | `33554432` | Hard response body limit |
| `VALIDATION_BATCH_SIZE` | `250` | CVEs rotated through validation per refresh |
| `NVD_RESULTS_PER_PAGE` | `500` | NVD page size |
| `NVD_API_KEY` | empty | Optional NVD API key |
| `GITHUB_TOKEN` | empty | Optional GitHub token for higher API limits |
| `ADMIN_TOKEN` | empty | Manual refresh token; required on public binds |
| `ADMIN_TOKEN_FILE` | empty | Read the administrator token from an injected secret file; conflicts with `ADMIN_TOKEN` |
| `DEMO_MODE` | `false` | Deterministic synthetic dataset; disables upstream refresh and requires separate data |
| `REFRESH_ENABLED` | `true` | Enable scheduled/manual ingestion in live mode |
| `NEWS_RETENTION_DAYS` | `730` | News retention; `0` disables deletion |

## API

### Health and operations

```text
GET  /health
GET  /ready
GET  /metrics
GET  /api/v1/stats
GET  /api/v1/sources
POST /api/v1/refresh
GET  /api/v1/refresh/status
```

Manual refresh authentication accepts either:

```text
Authorization: Bearer <ADMIN_TOKEN>
```

or:

```text
X-Admin-Token: <ADMIN_TOKEN>
```

### Intelligence queries

```text
GET /api/v1/items
GET /api/v1/items/{id}
GET /api/v1/cves/{cve_id}
GET /api/v1/cves/{cve_id}/evidence
```

Supported item filters:

```text
kind=news|cve
category=<category>
severity=critical|high|medium|low|none|unknown
confidence=very-high|high|medium|low|rejected
source=<partial source name>
region=<partial region>
q=<search text>
exploited=true|false
limit=1..200
offset=<integer>
cursor=<opaque cursor>
```

Examples:

```bash
curl 'http://127.0.0.1:8080/api/v1/items?kind=cve&severity=critical'
curl 'http://127.0.0.1:8080/api/v1/items?exploited=true&confidence=high'
curl 'http://127.0.0.1:8080/api/v1/items?category=ransomware'
curl 'http://127.0.0.1:8080/api/v1/cves/CVE-2026-1234/evidence'
```

## Cross-validation model

Each source keeps its own assertion in `cve_evidence`. The merged CVE display record does not erase conflicting evidence.

Validation records track:

- Number of independent sources
- Number of authoritative sources
- Canonical CVE status
- Severity and material CVSS disagreement
- Exploitation claims not corroborated by CISA KEV
- Missing canonical records
- EPSS probability and percentile

EPSS is retained as risk enrichment and does not count as independent confirmation of a CVE record.

## Extending the server

Implement `SourceAdapter`, register it in `build_registry`, and return normalized `ItemInput` and `EvidenceInput` values. Adapter output is validated before any database write.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the lifecycle, extension contract, failure boundaries, and storage model.

## Upgrade and database safety

Use [database-aware backup and guarded restore](deploy/README.md) before replacing a build. A raw copy of an active database may omit WAL state. Restore to a new file while the app is stopped, then select it through configuration. Schema compatibility must be checked before rolling back an image; one replica and a Recreate rollout are deliberate storage constraints.

The distribution archive intentionally excludes:

- `.env`
- database files and WAL/SHM files
- `target/`
- editor state
- Git metadata

Unpacking a newer source archive therefore does not overwrite local configuration or database data.

## Troubleshooting

### CISA reports invalid JSON

The adapter validates the official CISA endpoint and automatically attempts the CISA GitHub mirror. Error logs include endpoint-specific validation details. Verify that a proxy, captive portal, or TLS inspection product is not replacing the response body.

### NVD times out or returns an invalid response

Set an NVD API key, reduce `NVD_RESULTS_PER_PAGE`, and inspect the sanitized endpoint/status error in the server log:

```dotenv
NVD_API_KEY=your-key
NVD_RESULTS_PER_PAGE=250
SOURCE_TIMEOUT_SECONDS=180
```

The NVD cursor advances only after the complete page set is committed.

### A feed repeatedly fails

Check `/api/v1/sources`. Repeated failures trigger exponential backoff. Disable a persistently invalid feed with `DISABLED_SOURCES`, or replace its definition through `SOURCE_CONFIG_PATH`.

## Security notes

- Keep the default loopback bind when the dashboard is for one machine.
- Set a strong `ADMIN_TOKEN` or mounted `ADMIN_TOKEN_FILE` before any non-loopback bind.
- Put TLS and authentication in a trusted reverse proxy for network deployments.
- Treat feed and advisory content as untrusted data.
- Verify database-aware backups before upgrades; measure recovery in a disposable lab.
- Do not commit `.env`, API keys, or database files.

## License

MIT. See `LICENSE`.
