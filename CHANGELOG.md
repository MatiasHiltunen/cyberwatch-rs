# Changelog

## Unreleased — YAMK example, 2026-09-08

- Added deterministic offline demo with database mode isolation and visible synthetic-data labeling.
- Required strong public-bind administrative secrets, supported mounted secret files, and restricted outbound DNS/redirect destinations.
- Added bounded API admission, database-aware readiness, request metrics and regression tests.
- Fixed stale dashboard filter responses and protected credential-bearing API redirects.
- Added restricted containers, Kubernetes/Rahti resources, recovery tooling and local monitoring.
- Added security CI, scanned-and-tested image promotion, provenance checks and scoped deployment rollback.
- Mapped both course definitions to working artifacts, explicit evidence gaps, threats, risks, decisions and personal evidence templates.
- Verified native Rust/API, Python recovery/policy, process smoke and source security checks; hosted/container evidence remains pending.

## 0.4.1 — 2026-08-27

### Corrected

- Rebuilt the distribution from the complete project source tree.
- Added archive assertions preventing documentation-only bundles.
- Corrected generic environment parsing for string defaults.
- Removed a refresh status race between queue insertion and worker receipt.
- Corrected borrowed feed timestamp handling.
- Added explicit JSON 404 responses for unknown API routes.
- Allowed database filenames without an explicit parent directory.

### Improved

- Added CISA catalog content-hash caching.
- Persisted updated feed cache validators when content is unchanged.
- Required an administrative token for manual refresh on public binds.
- Removed unused dependencies and narrowed Clippy’s blocking lint set.
- Added verified packaging, checksum output, toolchain pinning, license, and release documentation.

## 0.4.0

- Added modular source adapters, bounded concurrent ingestion, local Turso/libSQL storage, cross-validation, source health, cursor pagination, and the bundled dashboard.
