# Code Review Report

**Historical report from the imported 0.4.1 bundle.** The observations and assembly
environment below describe that import, not the current course example. Current
security findings and verification are in [docs/security/findings.md](docs/security/findings.md)
and [RELEASE_STATUS.md](RELEASE_STATUS.md).

## Scope

This review covered the reconstructed Rust crate, database schema, source adapters, refresh coordination, API, browser client, Docker assets, CI, and packaging path.

## Critical packaging issue corrected

The previous distribution ZIP was built from a documentation staging directory and contained no Rust crate. The corrected release adds `tools/package.py`, which refuses to create an archive unless it contains the required Rust source files, schema, adapters, web client, and README. The finished archive is reopened, CRC-tested, and checked for a minimum Rust-source count.

## Correctness fixes

### Environment configuration type inference

String defaults passed through the generic environment parser were changed to owned `String` values. This avoids attempting to infer `FromStr` for `&str` during compilation.

### Refresh queue state race

Refresh status is now written as `queued` before the request can be received by the worker. A failed queue insertion restores idle status. This prevents a fast worker from setting `running` and then being overwritten by a late `queued` write.

### Feed timestamp borrowing

Feed timestamps are converted through borrowed `Option` values, avoiding moves out of borrowed feed entries.

### CISA unchanged-catalog writes

A validated CISA catalog hash is persisted. Unchanged catalogs update cache validators but skip parsing and thousands of repeated item/evidence upserts.

### Feed cache validators

When a feed body hash is unchanged but its `ETag` or `Last-Modified` value changes, the new validators are now persisted.

### Public refresh authorization

A server bound to a non-loopback address requires `ADMIN_TOKEN` for manual refresh. Scheduled ingestion is unaffected.

### API fallback behavior

Unknown `/api` routes now return a JSON 404 instead of falling through to the single-page application.

### Database path handling

A database filename with no explicit parent directory no longer attempts to create an empty path.

## Resilience and security retained

- Shared bounded HTTP transport
- Streaming response-size enforcement
- Source retries and deadlines
- Adapter panic isolation
- Exponential source backoff
- Transactional batch persistence
- Stable public API errors with detailed server logs
- Same-origin refresh protection
- Constant-time token comparison
- Strict security headers and CSP
- Bounded API pagination and query validation
- Token kept out of browser persistent storage

## Maintainability improvements

- Removed unused direct dependencies.
- Reduced Clippy gating to correctness lints so release checks are not blocked by subjective style warnings.
- Pinned the feed parser patch version used by the implementation.
- Added a pinned Rust toolchain file.
- Added an MIT license.
- Added a deterministic packaging entry point and checksum output.
- Added architecture, release status, and extension documentation.

## Validation completed in this environment

- Required-file manifest
- Cargo TOML parse and dependency presence
- JSON catalog parse, uniqueness, and source count
- SQLite schema application and integrity check
- Rust delimiter/string/comment structural scan
- Temporary-reference and merge-marker scan
- Browser JavaScript syntax through Node
- Secret, database, and build-artifact exclusion
- Distribution ZIP required-file manifest
- Distribution ZIP CRC test
- SHA-256 generation

## Validation not available in this environment

The container did not include `cargo`, `rustc`, Rustfmt, or Clippy, and external toolchain download was unavailable. Therefore, a real Rust compiler run could not be completed here. The included CI and `make check` commands are the final compiler gate before deployment.

## Remaining engineering considerations

1. The CVE Program validation stage performs bounded per-CVE HTTP requests. Very large installations may prefer a local mirror or bulk CVE-list ingestion.
2. Search currently uses indexed filters plus `LIKE`; high-volume deployments should consider SQLite FTS or an external search index.
3. The local embedded database intentionally serializes writes. Multiple independent writer processes require distributed job ownership and a different repository implementation.
4. Source URLs change over time. Source health monitoring and catalog maintenance remain operational responsibilities.
5. Back up existing experimental databases before upgrade because hand-edited legacy schemas cannot be inferred safely.
