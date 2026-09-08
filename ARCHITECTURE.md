# Cyberwatch RS Architecture

## 1. Design goals

Cyberwatch RS is designed as a local-first intelligence service that can grow in source count and record volume without turning each integration into a special case.

The primary goals are:

1. Keep source failures isolated.
2. Preserve source-specific evidence instead of hiding disagreement.
3. Bound network, memory, CPU, and write concurrency.
4. Make new sources implement one small adapter contract.
5. Keep the browser client deployable with the Rust binary.
6. Retain a simple local operational model.

## 2. Runtime components

```text
Scheduler / API
      |
      v
RefreshCoordinator ---- coalesces duplicate requests
      |
      v
SourceRegistry -------- Arc<dyn SourceAdapter>
      |
      +--> NVD adapter
      +--> CISA KEV adapter
      +--> GitHub advisory adapter
      +--> configured feed adapters
      |
      v
Output validation
      |
      v
Repository transaction ---- local Turso/libSQL file
      |
      v
CVE Program + EPSS validation rotation
      |
      v
Axum JSON API + static web dashboard
```

## 3. Source adapter contract

A source implements:

```rust
#[async_trait]
pub trait SourceAdapter: Send + Sync {
    fn descriptor(&self) -> SourceDescriptor;
    async fn run(&self, context: &SourceContext) -> anyhow::Result<SourceOutput>;
}
```

`SourceContext` provides shared, cloneable infrastructure:

- Validated configuration
- Repository handle
- Shared `reqwest::Client`

`SourceOutput` contains a normalized `IngestBatch`, source counters, skip state, and an optional operational note.

### Registration

Register an adapter in `src/ingest/mod.rs`:

```rust
if config.source_enabled("vendor-example") {
    registry.register(VendorExampleSource)?;
}
```

The registry rejects duplicate IDs before the server starts.

### Output rules

Before persistence, adapter output is checked for:

- Non-empty and bounded item IDs
- Supported item kinds
- Matching source IDs
- Valid HTTP/HTTPS URLs
- Valid CVSS ranges
- Valid CVE identifiers
- Duplicate news IDs within one output

A validation failure rejects the entire source batch atomically.

## 4. Refresh lifecycle

`RefreshCoordinator` owns a bounded MPSC queue and an observable status document.

- Concurrent manual and scheduled requests are coalesced while a job is queued or running.
- Status is set before the worker can receive a queued request, avoiding an observable queued/running race.
- Each source runs behind a semaphore.
- Each adapter has a hard execution deadline.
- Panics are caught at the adapter boundary.
- Source failures are recorded and enter exponential backoff.
- An individual source failure becomes a report entry rather than cancelling the refresh.

After source ingestion, a bounded rotating set of CVEs is cross-validated and retention cleanup is applied.

## 5. HTTP safety boundaries

`send_limited` provides common source transport behavior:

- Per-request timeout
- Bounded retries with exponential delay
- Response `Content-Length` pre-check
- Streaming hard body limit
- Sanitized status/content-type diagnostics without URL query/path or response-body disclosure
- Optional conditional request support

Outbound destination, redirect and resolved-address checks reject private/local targets and URL credentials. HTTPS downgrade is rejected; credential-bearing NVD/GitHub requests pin redirects to their original origin. The client does not inherit ambient proxy settings. Platform egress policy remains a separate boundary that the actual deployment must validate.

API middleware bounds concurrent admitted requests, handler execution time and URI/query size. Health/readiness probes have short deadlines. Metrics use bounded route/status labels instead of user-controlled URL values. Non-loopback startup requires a strong administrator token, secret file/value conflicts fail configuration, and secret values are redacted from configuration diagnostics.

Feeds use `ETag`, `Last-Modified`, and a content hash. Parsing is moved to `spawn_blocking` so XML parsing does not occupy Tokio worker threads.

CISA KEV also stores a catalog content hash, avoiding thousands of unchanged database upserts on every schedule.

## 6. Storage model

### `items`

The user-facing merged news and CVE records. CVE records use a stable `cve:<CVE-ID>` key, allowing higher-trust evidence to enrich a single display record.

### `item_categories`

Many-to-many normalized categories.

### `item_cves`

CVE mentions attached to news and advisory items.

### `cve_evidence`

One assertion per CVE, source, and evidence type. This is the audit trail used for cross-validation.

### `cve_validation`

Derived confidence and disagreement state. EPSS is stored here as enrichment and is intentionally excluded from source-count confidence.

### `ingestion_runs`

Per-source operational history.

### `sync_state`

Incremental cursors and source backoff state.

### `source_cache`

Conditional-request metadata and response content hashes.

## 7. Write strategy

The embedded database follows a single-writer model. `Repository` therefore uses a local write gate and `BEGIN IMMEDIATE` transactions for deterministic writes.

Network ingestion remains concurrent, while completed batches queue briefly at the persistence boundary. Each source batch writes atomically:

- Items
- Categories
- CVE links
- Evidence
- Source cursors
- Cache validators

A cursor is never committed independently from the corresponding records.

## 8. Query scalability

The main list endpoint supports opaque keyset cursors ordered by effective timestamp and item ID. Offset pagination remains available for small administrative queries, but large offsets are rejected by the API.

Indexes cover:

- Effective timestamp
- Item kind and time
- CVE ID
- Severity
- Exploitation state
- Source
- Categories
- Evidence source/CVE
- Validation confidence/time
- Ingestion history

## 9. Cross-validation semantics

Confidence considers distinct evidence sources and authoritative evidence sources.

- `very-high`: multiple authoritative sources plus broader corroboration
- `high`: strong authoritative or multi-source corroboration
- `medium`: at least one authoritative source or two independent sources
- `low`: a single non-authoritative source
- `rejected`: canonical CVE status is rejected

The validator separately exposes:

- Severity disagreement
- CVSS difference of at least 1.0
- Uncorroborated exploitation claims
- Missing canonical record
- EPSS probability and percentile

These fields are meant to support analyst judgment, not replace it.

## 10. Web client

The client is plain HTML, CSS, and JavaScript served by `tower-http`.

It uses only same-origin API requests, validates external link protocols, aborts superseded searches, keeps the administrative token in memory only, and presents source health, filterable intelligence, CVE details, and refresh state.

## 10a. Deterministic demonstration and operations

`DEMO_MODE=true` seeds explicitly synthetic records, disables all live refresh, and marks the database mode to reject accidental live/demo reuse. The browser and `/health` identify demo state. `/ready` verifies database access; `/metrics` exports HTTP counters/latency and refresh mode. A healthy demo proves API behavior, not live source freshness.

The executable's `--healthcheck` mode probes `/ready` using synchronous TCP with bounded reads and timeouts. It runs before configuration, database, or Tokio initialization and returns failure for an unavailable listener or schema. It uses process `BIND_ADDRESS` (default `127.0.0.1:8080`), maps wildcard binds to loopback, and does not load `.env`. Docker invokes this mode without adding a separate HTTP client to the image.

The deployment is one replica with a persistent volume and Recreate updates. In-process write serialization is not cross-process coordination, and ReadWriteOnce does not guarantee one process. Recovery uses the database-aware tooling and a new restore path while the application is stopped. See [deployment](deploy/README.md), [operations](docs/operations.md), and [architecture decisions](docs/adr/README.md).

## 10b. Production footprint and artifact boundaries

| Image | Contents and purpose |
|---|---|
| Docker `production` target (default) | Pinned distroless C/C++ runtime, Rust executable, dashboard assets, and license; runs as non-root with no shell, package manager, compiler, or Python |
| Docker `maintenance` target | Separate pinned Python image and database backup/restore tool; built and scanned independently for recovery operations |
| `.devcontainer/` | Rust, Python, Node, editors' tooling, and compiler cache for development; built from its own Dockerfile |

The Rust release profile uses `opt-level = "s"`, full LTO, one codegen unit, and symbol stripping. `panic = "unwind"` preserves the adapter boundary's `catch_unwind` behavior. Explicit dependency features remove unused functionality; server response compression uses gzip while ingestion retains Brotli/deflate/gzip decoding and HTTP/2.

`tools/runtime_artifact.py` exports an allowlist from the actual production image: the executable, `web/index.html`, `web/app.js`, `web/styles.css`, and license. Its Linux amd64/arm64 archive is dynamically linked and requires compatible host glibc/libgcc; it contains no source, documents, tests, database, or maintenance tooling. Source/course packaging remains a separate operation. CI gates payload contents, architecture, and size, and release attests the runtime archive and each image separately. See [production size](docs/production-size.md) for measurements and the enforced policy.

## 11. Extension checklist

When adding a structured source:

1. Choose a stable lowercase source ID.
2. Implement `SourceAdapter` in a dedicated module.
3. Use the shared HTTP helper and body limits.
4. Map data into normalized items and evidence.
5. Mark evidence authoritative only when the source owns that assertion.
6. Add incremental cursor or content-hash behavior where possible.
7. Register the adapter conditionally.
8. Add parser and validation tests with local fixtures.
9. Document any new environment variables.
10. Run `make check` and `make bundle`.

## 12. Scaling beyond one process

The current local mode intentionally serializes writes around one embedded database file. For substantially larger deployments, preserve the adapter and evidence contracts while replacing the repository layer with a service-backed implementation and distributed job ownership.

Useful next boundaries are:

- Separate ingestion workers from the API process
- Durable job queue and leases
- Object storage for raw payload archives
- Full-text search service or SQLite FTS migration
- Distributed tracing/OpenTelemetry export beyond the existing HTTP metrics
- Per-tenant source policy

The current module boundaries allow those changes without rewriting each source parser.
